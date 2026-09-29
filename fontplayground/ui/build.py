"""BuildController: what the action bar's buttons do. Build the font when needed, then install it or save a copy.

The model owns the combine lifecycle (worker, temp result, stale); this controller adds what happens around it:
it starts a build for an install or a save when there is no fresh result, performs that intent when the result
arrives, remembers what it installed or saved, and says in plain words what went wrong. It has no widgets, so
the action bar (and the tests) only read its state and call its methods.

Installing stages the result under its own name (`<Family>-<Style>.ttf`, the stem smart.default_output_path
proposes) so the user's font folder gets a readable file name, then hands it to the installer (ui.install, or a
fake in tests). Before an install, conflict() tells whether the name clashes with a font the user already has.
"""
from __future__ import annotations

import os
import shutil
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from fontplayground.ui import install, smart
from fontplayground.ui import model as model_module
from fontplayground.ui.model import ForgeModel

# Where a result is staged under its install name; None -> RESULT_DIR / STAGE_SUBDIR, read when it is needed
# (so a test that moves RESULT_DIR moves the staging folder too).
STAGE_DIR: Path | None = None
STAGE_SUBDIR = "install"

STOPPING_TEXT = "Stopping…"
BUILD_FAILED_TEXT = "Couldn't build the font: {error}"
INSTALL_FAILED_TEXT = "Couldn't install the font: {error}"
SAVE_FAILED_TEXT = "Couldn't save the font: {error}"
REMOVE_FAILED_TEXT = "Couldn't remove the font: {error}"
REPLACE_FAILED_TEXT = "Installed “{name}”, but couldn't remove “{previous}”: {error}"
REMOVED_TEXT = "Removed from your fonts."
NOT_INSTALLED_TEXT = "That font was no longer installed."
WINDOWS_HAS_TEXT = "Windows already has a font called “{name}” — choose another name."
YOU_HAVE_TEXT = "You already have a font called “{name}” installed — choose another name."
REPLACE_TEXT = "Replace the “{name}” you installed earlier?"

NO_CONFLICT = ("none", "")


class BuildState(Enum):
    IDLE = "idle"              # nothing done yet (or undone: reset, uninstall)
    BUILDING = "building"      # the model is combining; `intent` says what follows
    BUILT = "built"            # a build nobody asked to install or save finished
    INSTALLED = "installed"
    SAVED = "saved"
    FAILED = "failed"          # build, install, save or uninstall went wrong; `error` says what
    CANCELLED = "cancelled"


def stage_dir() -> Path:
    """The folder a result is copied into under its install name before it is installed."""
    return STAGE_DIR if STAGE_DIR is not None else model_module.RESULT_DIR / STAGE_SUBDIR


def system_fonts_dir() -> Path:
    """The system-wide font folder (%WINDIR%\\Fonts)."""
    return Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


def _is_under(path, folder) -> bool:
    """True when `path` lies inside `folder` (case-insensitive on Windows, like the file system)."""
    try:
        p = os.path.normcase(os.path.abspath(path))
        f = os.path.normcase(os.path.abspath(folder))
        return os.path.commonpath([p, f]) == f
    except ValueError:  # different drives
        return False


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


class BuildController(QObject):
    changed = Signal()   # anything the action bar shows may be different now

    def __init__(self, model: ForgeModel, installer=install, parent: QObject | None = None,
                 windows_fonts_dir: str | Path | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.installer = installer
        self.windows_fonts_dir = Path(windows_fonts_dir) if windows_fonts_dir is not None else system_fonts_dir()
        self._clear()
        model.progress.connect(self._on_progress)
        model.busyChanged.connect(self._on_busy_changed)
        model.resultReady.connect(self._on_result_ready)
        model.resultFailed.connect(self._on_result_failed)
        model.resultCancelled.connect(self._on_result_cancelled)
        model.resultStale.connect(self.changed)
        model.materialsChanged.connect(self.changed)
        model.namesChanged.connect(self.changed)
        model.resetDone.connect(self.reset)

    def _clear(self) -> None:
        self.state = BuildState.IDLE
        self.intent: str | None = None            # "install" | "save" while building for one of them
        self.stage = ""                           # plain-language progress text from the model
        self.fraction = 0.0
        self.installed_name: str | None = None    # full name this controller installed (and has not removed)
        self.installed_path: Path | None = None   # where the installer put it
        self.saved_path: Path | None = None
        self.error: str | None = None             # one line for the bar
        self.error_detail: str | None = None      # everything (a traceback for build failures)
        self.report = None                        # the last ForgeReport
        self.notice: str | None = None            # a short word after an uninstall
        self._installed_result: str | None = None  # the model result the install was made from
        self._save_path: Path | None = None       # where a save waiting for its build goes
        self._stopping = False
        self._ignore_run = False                  # a run still ending after a reset belongs to the old state

    # ----- reading -----
    @property
    def stopping(self) -> bool:
        """True between cancel() and the model's word that the build has stopped."""
        return self._stopping

    def can_install(self) -> bool:
        """False where installing is not supported: the bar then only offers to save the font."""
        try:
            return bool(self.installer.is_supported())
        except Exception:
            return False

    def is_update(self) -> bool:
        """True when a font was installed but what would be built now differs from it (the result went stale, or
        a newer result is not the one installed)."""
        if self.installed_name is None:
            return False
        return self.model.is_stale or self.model.result_path != self._installed_result

    def shown_file(self) -> Path | None:
        """The file "Show file" points at: the saved copy after a save, else the installed file (None: neither)."""
        if self.state is BuildState.SAVED and self.saved_path is not None:
            return self.saved_path
        return self.installed_path or self.saved_path

    def conflict(self) -> tuple[str, str]:
        """Whether installing the current family and style clashes with a font the user already has.

        ("block", message): a Windows font or one the user installed some other way has this family (English or
        native name) — installing would mix the two, so the user must choose another name. ("replace", message):
        a font this app forged earlier has this family and style (in the catalog, or registered under the full
        name) — installing replaces it, so ask first. ("none", ""): go ahead (also when this controller installed
        the name itself). Fonts whose file has vanished since the scan never count.
        """
        m = self.model
        family, full = m.family.strip(), f"{m.family} {m.style}".strip()
        if self.installed_name is not None and self.installed_name.casefold() == full.casefold():
            return NO_CONFLICT
        try:
            user_dir = self.installer.user_fonts_dir()
        except Exception:
            user_dir = None
        replace = False
        for face in m.catalog.values():
            names = {n.strip().casefold() for n in (face.family, *face.local_names)}   # apps match native names too
            if family.casefold() not in names or not os.path.isfile(face.path):
                continue
            if _is_under(face.path, self.windows_fonts_dir):
                return "block", WINDOWS_HAS_TEXT.format(name=family)
            if user_dir is not None and _is_under(face.path, user_dir):
                if not self.installer.is_forged(face.path):
                    return "block", YOU_HAVE_TEXT.format(name=family)
                # a forged font of another style is another file under another name: nothing is replaced
                replace = replace or face.style.strip().casefold() == m.style.strip().casefold()
        try:
            registered = self.installer.installed_path(full)
        except (install.InstallNotSupported, OSError):
            registered = None
        if registered is not None and os.path.isfile(registered):   # a registration whose file is gone is no font
            if not self.installer.is_forged(registered):
                return "block", YOU_HAVE_TEXT.format(name=full)
            replace = True
        return ("replace", REPLACE_TEXT.format(name=full)) if replace else NO_CONFLICT

    # ----- actions -----
    def install(self) -> None:
        """Install the font for the user: at once when the result is fresh, else after building it.
        Ignored while a build runs or when the recipe cannot be built."""
        if not self._can_act():
            return
        if self._fresh_result():
            self._install_result()
        else:
            self._build_for("install")

    def save_copy(self, path) -> None:
        """Save the font to `path`: at once when the result is fresh, else after building it."""
        if not self._can_act():
            return
        if self._fresh_result():
            self._save_result(Path(path))
        else:
            self._save_path = Path(path)
            self._build_for("save")

    def cancel(self) -> None:
        """Stop a running build; the state becomes CANCELLED once the model reports it."""
        if self.model.cancel():
            self._stopping = True
            self.stage = STOPPING_TEXT
            self.changed.emit()

    def uninstall(self) -> None:
        """Remove the font this controller installed. Nothing happens when it installed none."""
        if self.installed_name is None:
            return
        try:
            removed = self.installer.uninstall_font_for_user(self.installed_name)
        except Exception as e:  # not supported here, a registry refusal…
            self._fail(REMOVE_FAILED_TEXT.format(error=e))
            return
        self._forget_install()
        self.error = self.error_detail = None
        self.notice = REMOVED_TEXT if removed else NOT_INSTALLED_TEXT
        self.state = BuildState.IDLE
        self.changed.emit()

    def reset(self) -> None:
        """Back to a fresh start (the model was reset). A build still ending belongs to the old state."""
        busy = self.model.is_busy()
        self._clear()
        self._ignore_run = busy
        self.changed.emit()

    # ----- internals -----
    def _can_act(self) -> bool:
        return not self.model.is_busy() and self.state is not BuildState.BUILDING and not self.model.validity()

    def _fresh_result(self) -> bool:
        path = self.model.result_path
        return path is not None and not self.model.is_stale and os.path.isfile(path)

    def _build_for(self, intent: str | None) -> None:
        previous = self.state
        self._enter_building(intent)
        if not self.model.combine():   # cannot happen after _can_act(); keep the bar honest if it does
            self.state, self.intent, self._save_path = previous, None, None
            self.changed.emit()

    def _enter_building(self, intent: str | None) -> None:
        self.state = BuildState.BUILDING
        self.intent = intent
        self.stage, self.fraction = "", 0.0
        self.error = self.error_detail = self.notice = None
        self._stopping = False
        self.changed.emit()

    def _install_result(self) -> None:
        m = self.model
        full = f"{m.family} {m.style}".strip()
        previous = self.installed_name
        staged: Path | None = None
        try:
            folder = stage_dir()
            folder.mkdir(parents=True, exist_ok=True)
            staged = folder / f"{smart.default_output_path(m.family, m.style).stem}.ttf"
            shutil.copyfile(m.result_path, staged)
            dest = self.installer.install_font_for_user(staged, full)
        except Exception as e:  # not supported here, a locked file, a registry refusal…
            self._fail(INSTALL_FAILED_TEXT.format(error=e))
            return
        finally:
            if staged is not None:
                try:
                    staged.unlink()
                except OSError:
                    pass
        if previous is not None and previous.casefold() != full.casefold():
            try:   # "Update installed font" under a new name: the old one is replaced, not kept beside it
                self.installer.uninstall_font_for_user(previous)
            except Exception as e:  # keep the old name on record: Update tries to replace it again
                self._fail(REPLACE_FAILED_TEXT.format(name=full, previous=previous, error=e))
                return
        self.installed_name = full
        self.installed_path = Path(dest) if dest is not None else None
        self._installed_result = m.result_path
        self.error = self.error_detail = self.notice = None
        self.state = BuildState.INSTALLED
        self.changed.emit()

    def _save_result(self, path: Path) -> None:
        try:
            saved = self.model.save_to(path)
        except Exception as e:  # no result, a read-only folder, a full disk…
            self._fail(SAVE_FAILED_TEXT.format(error=e))
            return
        self.saved_path = Path(saved)
        self.error = self.error_detail = self.notice = None
        self.state = BuildState.SAVED
        self.model.set_output(str(saved), by_user=True)   # emits namesChanged -> changed
        self.changed.emit()

    def _forget_install(self) -> None:
        self.installed_name = self.installed_path = self._installed_result = None

    def _fail(self, message: str, detail: str | None = None) -> None:
        self.state = BuildState.FAILED
        self.intent = None
        self.error = _first_line(message)
        self.error_detail = detail if detail is not None else message
        self.changed.emit()

    def _end_run(self) -> bool:
        """A build ended: False when it belongs to the state before a reset (then it is ignored)."""
        self._stopping = False
        if self._ignore_run:
            self._ignore_run = False
            return False
        return True

    # ----- model signals -----
    def _on_busy_changed(self, busy: bool) -> None:
        if busy and self.state is not BuildState.BUILDING and not self._ignore_run:
            self._enter_building(None)   # a build someone else started (nothing to do when it ends)

    def _on_progress(self, text: str, fraction: float) -> None:
        if self.state is not BuildState.BUILDING or self._stopping:
            return
        self.stage, self.fraction = text, fraction
        self.changed.emit()

    def _on_result_ready(self, report) -> None:
        if not self._end_run():
            return
        self.report = report
        intent, self.intent = self.intent, None
        save_path, self._save_path = self._save_path, None
        if intent == "install":
            self._install_result()
        elif intent == "save" and save_path is not None:
            self._save_result(save_path)
        else:
            self.state = BuildState.BUILT
            self.changed.emit()

    def _on_result_failed(self, message: str) -> None:
        if not self._end_run():
            return
        self._save_path = None
        self._fail(BUILD_FAILED_TEXT.format(error=_first_line(message)), detail=message)

    def _on_result_cancelled(self) -> None:
        if not self._end_run():
            return
        self.state = BuildState.CANCELLED
        self.intent = self._save_path = None
        self.changed.emit()
