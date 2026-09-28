"""Per-user font install on Windows, no admin rights needed.

Installing = copy the file into the user's font folder, register it in the per-user font list in the registry,
tell the graphics system about it and broadcast "fonts changed" so running programs pick it up.
Uninstalling reverses those steps. Nothing here needs Qt.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

from fontplayground.engine.merge import FORGED_NOTICE

FONTS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
REGISTRY_SUFFIX = " (TrueType)"
WM_FONTCHANGE = 0x001D
HWND_BROADCAST = 0xFFFF
SMTO_ABORTIFHUNG = 0x0002
BROADCAST_TIMEOUT_MS = 1000
MAX_RENAMES = 99


class InstallNotSupported(RuntimeError):
    """Installing fonts for the current user is only implemented on Windows."""


def is_supported() -> bool:
    return sys.platform.startswith("win")


def user_fonts_dir() -> Path:
    """Where Windows keeps fonts installed for the current user only."""
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Microsoft" / "Windows" / "Fonts"


def registry_value_name(full_name: str) -> str:
    return full_name + REGISTRY_SUFFIX


def full_name_of(path: str | Path) -> str:
    """The font's full name as its name table states it (all faces joined with ' & ' for a collection)."""
    p = Path(path)
    if p.suffix.lower() in (".ttc", ".otc"):
        coll = TTCollection(str(p), lazy=True)
        try:
            names = [_full_name(f, p) for f in coll.fonts]
        finally:
            coll.close()
        return " & ".join(dict.fromkeys(names))  # unique, in order
    font = TTFont(str(p), lazy=True)
    try:
        return _full_name(font, p)
    finally:
        font.close()


def is_forged(path: str | Path) -> bool:
    """True when the file is a font this app forged (its name ID 0 starts with FORGED_NOTICE)."""
    try:
        font = TTFont(str(path), lazy=True, fontNumber=0)
    except Exception:  # missing, unreadable or not a font
        return False
    try:
        notice = font["name"].getDebugName(0) if "name" in font else None
    except Exception:
        return False
    finally:
        font.close()
    return bool(notice) and notice.startswith(FORGED_NOTICE)


def _full_name(font: TTFont, path: Path) -> str:
    name = font["name"] if "name" in font else None
    if name is None:
        return path.stem
    return name.getDebugName(4) or name.getBestFullName() or path.stem


def install_font_for_user(path: str | Path, full_name: str | None = None) -> Path:
    """Install a font file for the current user and return where it now lives.

    The file is copied into the user's font folder (overwriting an earlier copy; if that copy is in use and cannot
    be replaced, the new one is written as '<stem>-<n><suffix>' instead), registered as '<full name> (TrueType)',
    loaded, and every running program is told that the fonts changed.
    """
    _require_windows()
    import winreg

    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"Font file not found: {src}")
    full_name = full_name or full_name_of(src)
    value_name = registry_value_name(full_name)
    dest = _copy_into(src, user_fonts_dir())

    previous = _registered_path(value_name)
    if previous and Path(previous) != dest:
        _remove_font_resource(previous)  # the old registration pointed elsewhere; stop serving that file

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, FONTS_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(dest))
    _add_font_resource(dest)
    broadcast_font_change()
    return dest


def uninstall_font_for_user(full_name: str) -> bool:
    """Undo install_font_for_user for a font registered under this full name. False when it was not installed."""
    _require_windows()
    import winreg

    value_name = registry_value_name(full_name)
    installed = _registered_path(value_name)
    if installed is None:
        return False
    _remove_font_resource(installed)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, FONTS_KEY, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, value_name)
        except FileNotFoundError:
            pass
    _delete_file(Path(installed))
    broadcast_font_change()
    return True


def installed_path(full_name: str) -> Path | None:
    """The file registered for this full name in the user's font list, or None."""
    _require_windows()
    found = _registered_path(registry_value_name(full_name))
    return Path(found) if found else None


def broadcast_font_change() -> None:
    """Tell every top-level window that the set of fonts changed (waits at most a second for hung ones)."""
    _require_windows()
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    send = user32.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                     ctypes.c_void_p]
    send.restype = wintypes.LPARAM
    send(HWND_BROADCAST, WM_FONTCHANGE, 0, 0, SMTO_ABORTIFHUNG, BROADCAST_TIMEOUT_MS, None)


# ----- internals -----
def _require_windows() -> None:
    if not is_supported():
        raise InstallNotSupported("Installing fonts for the current user is only supported on Windows.")


def _copy_into(src: Path, dest_dir: Path) -> Path:
    """Copy src into dest_dir under its own name, overwriting; fall back to '<stem>-<n><suffix>' when it is locked."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidates = [dest_dir / src.name] + [dest_dir / f"{src.stem}-{n}{src.suffix}" for n in range(1, MAX_RENAMES + 1)]
    last_error: OSError | None = None
    for dest in candidates:
        if dest.exists() and _same_file(src, dest):
            return dest  # installing from the font folder itself: already in place
        try:
            shutil.copyfile(src, dest)
            return dest
        except OSError as e:  # locked by a program using the font, or otherwise not replaceable
            last_error = e
    raise last_error if last_error else OSError(f"Could not copy {src} into {dest_dir}")


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _registered_path(value_name: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, FONTS_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return None
    return str(value) if value else None


def _gdi32():
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.windll.gdi32
    gdi32.AddFontResourceW.argtypes = [wintypes.LPCWSTR]
    gdi32.AddFontResourceW.restype = ctypes.c_int
    gdi32.RemoveFontResourceW.argtypes = [wintypes.LPCWSTR]
    gdi32.RemoveFontResourceW.restype = wintypes.BOOL
    return gdi32


def _add_font_resource(path: Path) -> int:
    return int(_gdi32().AddFontResourceW(str(path)))


def _remove_font_resource(path: str | Path) -> None:
    """Unload the file; the graphics system counts loads, so keep going until it reports nothing left to remove."""
    gdi32 = _gdi32()
    for _ in range(16):
        if not gdi32.RemoveFontResourceW(str(path)):
            break


def _delete_file(path: Path) -> bool:
    for attempt in range(5):  # the graphics system can hold the file for a moment after it was unloaded
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.1 * (attempt + 1))
    return False
