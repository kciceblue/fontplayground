"""Main window: step rail + the three workflow pages + the materials tray."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from fontplayground.catalog.cache import CatalogCache
from fontplayground.paths import config_dir, default_font_dirs
from fontplayground.ui.check_page import CheckPage
from fontplayground.ui.forge_page import ForgePage
from fontplayground.ui.model import ForgeModel, clean_stale_results
from fontplayground.ui.pick_page import PickPage
from fontplayground.ui.preview import PreviewWidget
from fontplayground.ui.rail import StepRail
from fontplayground.ui.tray import MaterialsTray
from fontplayground.ui.workers import ScanWorker

PICK, CHECK, FORGE = 0, 1, 2
COMBINE_WAIT_MS = 180_000   # closing waits this long for a cancelled forge to reach its next stage boundary
SCAN_WAIT_MS = 3_000        # closing waits this long for an interrupted scan to stop
QUIT_QUESTION = "A forge is still running. Quit anyway?"
APP_STYLE = """
QMainWindow { background: #fafafa; }
QStatusBar { background: #ffffff; border-top: 1px solid #e3e3e3; }
"""


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class MainWindow(QMainWindow):
    def __init__(self, font_dirs: list[Path], config_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Font Playground")
        self.setStyleSheet(APP_STYLE)
        self.font_dirs = [Path(d) for d in font_dirs]
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache = CatalogCache(self.config_dir / "catalog.json")
        self.cache.load()
        self.settings_path = self.config_dir / "settings.json"
        self.forge_settings_path = self.config_dir / "forge_last.json"
        self._settings = _read_json(self.settings_path, {"extra_dirs": []})
        self._pending_restore = _read_json(self.forge_settings_path, None)
        self._pending_scan: bool | None = None
        self._closing = False
        self._restoring = False
        self.scan_worker: ScanWorker | None = None
        clean_stale_results()

        self.model = ForgeModel(self)
        self.previews = [PreviewWidget() for _ in range(3)]
        self.pick_page = PickPage(self.model, self.previews[PICK])
        self.check_page = CheckPage(self.model, self.previews[CHECK])
        self.forge_page = ForgePage(self.model, self.previews[FORGE])
        self.rail = StepRail()
        self.stack = QStackedWidget()
        for page in (self.pick_page, self.check_page, self.forge_page):
            self.stack.addWidget(page)
        self.tray = MaterialsTray(self.model)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.rail)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.tray)
        self.setCentralWidget(central)
        self.statusBar()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(self.save_forge_settings)

        self.rail.stepClicked.connect(self.go)
        self.rail.rescan_action.triggered.connect(lambda: self.start_scan(use_cache=False))
        self.rail.add_folder_action.triggered.connect(self.add_folder)
        self.rail.start_over_action.triggered.connect(self.start_over)
        self.rail.open_settings_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.config_dir))))
        self.tray.backClicked.connect(lambda: self.go(self.step() - 1))
        self.tray.primaryClicked.connect(self._primary)
        self.tray.addClicked.connect(lambda: self.go(PICK))
        self.forge_page.startOverClicked.connect(self.start_over)
        self.forge_page.primaryStateChanged.connect(self._update_navigation)
        self.model.materialsChanged.connect(self._update_navigation)
        self.model.validityChanged.connect(self._update_navigation)
        self.model.busyChanged.connect(self._on_busy)
        for sig in (self.model.materialsChanged, self.model.namesChanged, self.model.sampleChanged):
            sig.connect(self._schedule_save)

        self.go(PICK)
        self.start_scan(use_cache=True)

    # ----- navigation -----
    def step(self) -> int:
        return self.stack.currentIndex()

    def go(self, step: int) -> None:
        step = max(PICK, min(FORGE, step))
        if step != self.step() and not self.rail.is_reachable(step):
            return
        self.stack.setCurrentIndex(step)
        self.rail.set_step(step)
        self.tray.set_back_visible(step > PICK)
        if step == FORGE:
            self.forge_page.activate()
        self._update_navigation()

    def _update_navigation(self, *_args) -> None:
        has_fonts = bool(self.model.rows)
        problem = self.model.validity()
        self.rail.set_reachable(CHECK, has_fonts)
        self.rail.set_reachable(FORGE, has_fonts and not problem)
        step = self.step()
        if step == PICK:
            self.tray.set_primary("Next: Check ›", has_fonts, "" if has_fonts else "Add at least one font.")
        elif step == CHECK:
            self.tray.set_primary("Next: Forge ›", not problem, problem)
        else:
            text, enabled = self.forge_page.primary_state()
            self.tray.set_primary(text, enabled)
        current = self.statusBar().currentMessage()
        if problem and has_fonts:
            self.statusBar().showMessage(problem)
        elif current and not current.endswith(("found", "skipped", "fonts…")):
            self.statusBar().clearMessage()

    def _primary(self) -> None:
        if self.step() < FORGE:
            self.go(self.step() + 1)
        else:
            self.forge_page.primary_clicked()

    def _on_busy(self, busy: bool) -> None:
        for i in (PICK, CHECK):
            self.rail.buttons[i].setEnabled((not busy or i == self.step()) and self.rail.is_reachable(i))
        self.tray.list.setEnabled(not busy)
        self.tray.add_button.setEnabled(not busy)
        self._update_navigation()

    def start_over(self) -> None:
        self.model.discard_result()
        for key in list(self.model.keys()):
            self.model.remove(key)
        self.go(PICK)

    # ----- scanning -----
    def all_dirs(self) -> list[Path]:
        return self.font_dirs + [Path(d) for d in self._settings.get("extra_dirs", [])]

    def start_scan(self, use_cache: bool) -> None:
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self._pending_scan = False if self._pending_scan is False else use_cache
            return
        self.pick_page.begin_scan()
        self.rail.rescan_action.setEnabled(False)
        self.rail.add_folder_action.setEnabled(False)
        self.statusBar().showMessage("Scanning fonts…")
        self.scan_worker = ScanWorker(self.all_dirs(), self.cache, use_cache, parent=self)
        self.scan_worker.face_found.connect(self.pick_page.add_face)
        self.scan_worker.progress.connect(self.pick_page.set_progress)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, result) -> None:
        if self._closing or (self.scan_worker is not None and self.scan_worker.interrupted):
            return
        self.pick_page.end_scan(result)
        self.rail.rescan_action.setEnabled(True)
        self.rail.add_folder_action.setEnabled(True)
        msg = f"{len(result.faces)} font faces found"
        if result.failed:
            msg += f", {len(result.failed)} unreadable files skipped"
        self.statusBar().showMessage(msg, 10000)
        faces = self.pick_page.faces_by_key()
        self._restoring = True
        try:
            self.model.set_catalog(faces)
            if self._pending_restore:
                self.model.from_settings(self._pending_restore, faces)
                self._pending_restore = None
        finally:
            self._restoring = False
        self._update_navigation()
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

    # ----- persistence -----
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
        if self._pending_restore is None:  # never overwrite settings that were not restored yet
            self.save_forge_settings()
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.interrupt()
            self.scan_worker.wait(SCAN_WAIT_MS)
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
    window.show()
    sys.exit(app.exec())
