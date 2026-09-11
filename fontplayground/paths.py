"""Per-OS font locations and the application's config directory."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "FontPlayground"
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".otc"}


def default_font_dirs(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> list[Path]:
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform.startswith("win"):
        dirs = [Path(env.get("WINDIR", r"C:\Windows")) / "Fonts"]
        local = env.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        return dirs
    if platform == "darwin":
        return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".fonts", home / ".local" / "share" / "fonts"]


def config_dir(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> Path:
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform.startswith("win"):
        return Path(env.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / APP_NAME
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    return home / ".config" / "fontplayground"


def is_font_file(path: Path) -> bool:
    return path.suffix.lower() in FONT_EXTENSIONS
