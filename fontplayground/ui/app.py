"""Main window: the one-screen mixer.

Left: the recipe ("Your font") or, while the user chooses a font, the font picker. Right: the preview pane,
editable and drawn in the fonts the result will use. Bottom: the action bar (name, Save a copy…, Install). The
window owns scanning, the ⋯ menu, settings and closing; every panel reads and changes the ForgeModel itself.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QMainWindow, QMenu, QMessageBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from fontplayground.catalog.cache import CatalogCache
from fontplayground.catalog.face import read_faces
from fontplayground.paths import config_dir, default_font_dirs
from fontplayground.ui import install, languages
from fontplayground.ui.action_bar import ActionBar
from fontplayground.ui.advanced import AdvancedDialog
from fontplayground.ui.build import BuildController
from fontplayground.ui.model import ForgeModel, clean_stale_results
from fontplayground.ui.picker import FontPicker
from fontplayground.ui.preview_pane import PreviewPane
from fontplayground.ui.recipe import RecipePanel
from fontplayground.ui.requests import PickRequest
from fontplayground.ui.theme import DEFAULT_PREFERENCE, PREFERENCES, Theme, ThemeManager
from fontplayground.ui.workers import ScanWorker

RECIPE, PICKER = 0, 1          # pages of the left column
LEFT_WIDTH = 420
DEFAULT_PREVIEW_SIZE = 30
PREVIEW_SIZES = (10, 96)
COMBINE_WAIT_MS = 180_000      # closing waits this long for a cancelled build to reach its next stage boundary
SCAN_WAIT_MS = 3_000           # closing waits this long for an interrupted scan to stop
QUIT_QUESTION = "Your font is still being built. Quit anyway?"
TRY_HINT = "↑ ↓ try the next font, Enter uses it."
THEME_LABELS = {"system": "System", "light": "Light", "dark": "Dark"}   # menu text per preference
APP_STYLE = """
QMainWindow { background: $window; }
QStackedWidget#left { background: $surface; border-right: 1px solid $border_soft; }
"""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def theme_preference(settings: dict) -> str:
    """The stored theme choice, or "system" when the file has none or something unexpected."""
    value = settings.get("theme")
    return value if value in PREFERENCES else DEFAULT_PREFERENCE


def preview_preferences(settings: dict) -> tuple[int, bool]:
    """(preview size in points, colour by font) from the settings, defaults for anything missing or odd."""
    size = settings.get("preview_size")
    if isinstance(size, bool) or not isinstance(size, int) or not PREVIEW_SIZES[0] <= size <= PREVIEW_SIZES[1]:
        size = DEFAULT_PREVIEW_SIZE
    return size, settings.get("colour_by_font") is True


def trial_text(family: str, language_id: str, replaced_family: str | None, first: bool) -> str:
    """The banner over the preview while the picker's current font is tried in."""
    if first:
        what = f"Trying {family} as your main font"
    elif replaced_family is not None:
        what = f"Trying {family} instead of {replaced_family}"
    elif language_id == languages.ANY:
        what = f"Trying {family}"
    else:
        what = f"Trying {family} for {languages.language(language_id).short_label}"
    return f"{what} — {TRY_HINT}"


class MainWindow(QMainWindow):
    def __init__(self, font_dirs: list[Path], config_dir: Path, parent=None, installer=install) -> None:
        super().__init__(parent)
        self.setWindowTitle("Font Playground")
        self.font_dirs = [Path(d) for d in font_dirs]
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache = CatalogCache(self.config_dir / "catalog.json")
        self.cache.load()
        self.settings_path = self.config_dir / "settings.json"
        self.forge_settings_path = self.config_dir / "forge_last.json"
        self._settings = _read_json(self.settings_path, {"extra_dirs": []})
        if not isinstance(self._settings, dict):
            self._settings = {"extra_dirs": []}
        self._pending_restore = _read_json(self.forge_settings_path, None)
        self._pending_scan: bool | None = None
        self._closing = False
        self._restoring = False
        self._request: PickRequest | None = None     # what the open picker was asked for
        self.scan_worker: ScanWorker | None = None
        self.advanced: AdvancedDialog | None = None
        clean_stale_results()

        # The manager pushes the palette before any widget exists, so every widget is born in the right colours.
        self.theme_manager = ThemeManager(theme_preference(self._settings), self)
        theme = self.theme_manager.theme
        self.setStyleSheet(theme.render(APP_STYLE))

        self.model = ForgeModel(self)
        self.controller = BuildController(self.model, installer, self)
        self.menu = self._build_menu()
        self.recipe = RecipePanel(self.model, theme=theme)
        self.picker = FontPicker(theme=theme)
        self.left = QStackedWidget()
        self.left.setObjectName("left")
        self.left.setFixedWidth(LEFT_WIDTH)
        self.left.addWidget(self.recipe)
        self.left.addWidget(self.picker)
        self.pane = PreviewPane(self.model, self.menu, theme=theme)
        self.bar = ActionBar(self.model, self.controller, theme=theme)
        self.pane.set_preferences(*preview_preferences(self._settings))

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.left)
        body.addWidget(self.pane, 1)
        outer.addLayout(body, 1)
        outer.addWidget(self.bar)
        self.setCentralWidget(central)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self.save_forge_settings)
        self._prefs_timer = QTimer(self)          # a slider drag writes settings.json once, when it stops
        self._prefs_timer.setSingleShot(True)
        self._prefs_timer.setInterval(300)
        self._prefs_timer.timeout.connect(self._write_settings)

        self.recipe.chooseRequested.connect(self.open_picker)
        self.recipe.advancedRequested.connect(self.show_advanced)
        self.pane.addForLanguage.connect(self._add_for_language)
        self.pane.preferencesChanged.connect(self._save_preferences)
        self.picker.candidateChanged.connect(self._try_candidate)
        self.picker.chosen.connect(self._use_face)
        self.picker.cancelled.connect(self.close_picker)
        self.bar.detailsRequested.connect(self.show_advanced)
        self.model.busyChanged.connect(self._on_busy)
        self.model.resultReady.connect(self._show_built)
        self.model.resultStale.connect(self.pane.clear_built)
        self.model.resetDone.connect(self.pane.clear_built)
        for sig in (self.model.materialsChanged, self.model.namesChanged, self.model.sampleChanged):
            sig.connect(self._schedule_save)
        self.theme_manager.changed.connect(self.apply_theme)

        self.left.setCurrentIndex(RECIPE)
        self.start_scan(use_cache=True)

    # ----- the ⋯ menu -----
    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        self.rescan_action = menu.addAction("Rescan fonts")
        self.rescan_action.triggered.connect(self._rescan)
        self.add_folder_action = menu.addAction("Add folder…")
        self.add_folder_action.triggered.connect(self.add_folder)
        menu.addSeparator()
        self.start_over_action = menu.addAction("Start over")
        self.start_over_action.triggered.connect(self.start_over)
        self.advanced_action = menu.addAction("Advanced…")
        self.advanced_action.triggered.connect(self.show_advanced)
        menu.addSeparator()
        self.theme_menu = menu.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for preference in PREFERENCES:
            action = QAction(THEME_LABELS[preference], self)
            action.setCheckable(True)
            action.setData(preference)
            self.theme_group.addAction(action)
            self.theme_menu.addAction(action)
            self.theme_actions[preference] = action
        self.theme_actions[self.theme_manager.preference].setChecked(True)
        self.theme_group.triggered.connect(self._on_theme_action)
        self.open_settings_action = menu.addAction("Open settings folder")
        self.open_settings_action.triggered.connect(self._open_settings_folder)
        return menu

    def _rescan(self) -> None:
        self.start_scan(use_cache=False)

    def _on_theme_action(self, action: QAction) -> None:
        self._choose_theme(action.data())

    def _open_settings_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_dir)))

    # ----- picking fonts -----
    def picker_is_open(self) -> bool:
        return self.left.currentIndex() == PICKER

    def open_picker(self, request: PickRequest) -> None:
        """Show the picker for `request`; the preview tries its current font until the user decides."""
        if self.model.is_busy():
            return
        self._request = request
        try:
            lang = languages.language(request.language)
        except KeyError:
            lang = languages.language(languages.ANY)
        text = languages.with_language_line(self.model.sample_text, lang)
        if text != self.model.sample_text:  # so trying fonts for the language shows something
            self.model.set_sample_text(text)
        adding = request.replace_key is None and bool(self.model.rows)
        suggestions = self.model.suggestions_for(lang.id) if adding else []
        self.left.setCurrentIndex(PICKER)
        self.picker.open(request, self.model.main, self.model.keys(), suggestions)
        self.picker.search.setFocus()

    def close_picker(self) -> None:
        self._request = None
        self.pane.clear_trial()
        self.left.setCurrentIndex(RECIPE)

    def _add_for_language(self, language_id: str) -> None:
        self.open_picker(PickRequest(language_id))

    def _try_candidate(self, face) -> None:
        request = self._request
        if request is None or face is None:
            self.pane.clear_trial()
            return
        language_id = self.picker.language()
        replaced = self.model.row(request.replace_key) if request.replace_key is not None else None
        first = not self.model.rows
        mix = self.model.mix_with(face, replace=request.replace_key,
                                  language=None if first or replaced is not None else language_id)
        self.pane.set_trial(mix, trial_text(face.family, language_id,
                                            replaced.face.family if replaced is not None else None, first))

    def _use_face(self, face) -> None:
        request = self._request
        if request is None:
            return
        language_id = self.picker.language()
        if request.replace_key is not None:
            self.model.replace(request.replace_key, face)
        elif not self.model.rows:
            self.model.add(face)       # the main font: nothing pinned, it simply comes first
        else:
            self.model.add(face, None if language_id == languages.ANY else language_id)
        self.close_picker()

    # ----- building -----
    def _on_busy(self, busy: bool) -> None:
        if busy and self.picker_is_open():
            self.close_picker()
        self.recipe.set_locked(busy)
        if self.advanced is not None:
            self.advanced.set_locked(busy)

    def _show_built(self, _report) -> None:
        """Draw the preview in the font that was just built (until something changes)."""
        path = self.model.result_path
        if not path or self.model.is_stale:
            return
        try:
            codepoints = read_faces(path)[0].codepoints
        except Exception:  # the file exists but cannot be read back: keep the mix
            logging.getLogger(__name__).exception("could not read the built font back")
            return
        self.pane.set_built(path, codepoints)

    def show_advanced(self) -> None:
        if self.advanced is None:
            self.advanced = AdvancedDialog(self.model, self.controller, self, theme=self.theme_manager.theme)
            self.advanced.set_locked(self.model.is_busy())
        self.advanced.show()
        self.advanced.raise_()
        self.advanced.activateWindow()

    def start_over(self) -> None:
        self.close_picker()
        self.model.reset()

    # ----- scanning -----
    def all_dirs(self) -> list[Path]:
        return self.font_dirs + [Path(d) for d in self._settings.get("extra_dirs", [])]

    def start_scan(self, use_cache: bool) -> None:
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self._pending_scan = False if self._pending_scan is False else use_cache
            return
        self.picker.begin_scan()
        self.rescan_action.setEnabled(False)
        self.add_folder_action.setEnabled(False)
        self.scan_worker = ScanWorker(self.all_dirs(), self.cache, use_cache, parent=self)
        self.scan_worker.face_found.connect(self.picker.add_face)
        self.scan_worker.progress.connect(self.picker.set_progress)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, result) -> None:
        if self._closing or (self.scan_worker is not None and self.scan_worker.interrupted):
            return
        self.picker.end_scan(result)
        self.rescan_action.setEnabled(True)
        self.add_folder_action.setEnabled(True)
        faces = self.picker.faces_by_key()
        self._restoring = True
        try:
            self.model.set_catalog(faces)
            if self._pending_restore:
                try:
                    self.model.from_settings(self._pending_restore, faces)
                except Exception:  # a hand-edited or damaged settings file must not take the app down
                    logging.getLogger(__name__).exception("could not restore the last settings")
                    self.model.reset()
                self._pending_restore = None
        finally:
            self._restoring = False
        if self._pending_scan is not None:
            use_cache, self._pending_scan = self._pending_scan, None
            self.scan_worker.wait()
            self.start_scan(use_cache)

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add font folder")
        if not folder:
            return
        extra = self._settings.setdefault("extra_dirs", [])
        if folder not in extra:
            extra.append(folder)
            _write_json(self.settings_path, self._settings)
        self.start_scan(use_cache=True)

    # ----- theme -----
    def apply_theme(self, theme: Theme) -> None:
        """Retint the window and every part of it (the manager has already pushed the palette)."""
        self.setStyleSheet(theme.render(APP_STYLE))
        for widget in (self.recipe, self.picker, self.pane, self.bar, self.advanced):
            if widget is not None:
                widget.apply_theme(theme)

    def _choose_theme(self, preference: str) -> None:
        self.theme_manager.preference = preference
        self._settings["theme"] = preference
        _write_json(self.settings_path, self._settings)

    # ----- persistence -----
    def _save_preferences(self, size: int, colour_by_font: bool) -> None:
        self._settings["preview_size"] = int(size)
        self._settings["colour_by_font"] = bool(colour_by_font)
        self._prefs_timer.start()

    def _write_settings(self) -> None:
        _write_json(self.settings_path, self._settings)

    def _schedule_save(self, *_args) -> None:
        if not self._restoring and not self._closing:
            self._save_timer.start()

    def save_forge_settings(self) -> None:
        if self._restoring:
            return
        _write_json(self.forge_settings_path, self.model.to_settings())

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.model.is_busy():
            answer = QMessageBox.question(self, "Font Playground", QUIT_QUESTION,
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.model.cancel(wait_ms=COMBINE_WAIT_MS)
        self._closing = True
        self._save_timer.stop()
        if self._prefs_timer.isActive():
            self._prefs_timer.stop()
            self._write_settings()
        if self._pending_restore is None:  # never overwrite settings that were not restored yet
            self.save_forge_settings()
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.interrupt()
            self.scan_worker.wait(SCAN_WAIT_MS)
        if self.advanced is not None:
            self.advanced.close()
        self.model.discard_result()
        super().closeEvent(event)


def main() -> None:
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # timestamp/version warnings are noise here
    app = QApplication(sys.argv)
    app.setApplicationName("Font Playground")
    if sys.platform.startswith("win"):
        app.setFont(QFont("Segoe UI", 10))
    window = MainWindow(default_font_dirs(), config_dir())
    window.resize(1280, 820)
    window.setMinimumSize(1000, 640)
    window.show()
    sys.exit(app.exec())
