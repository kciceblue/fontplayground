"""Main window: Fonts tab + Forge tab, scanning, and settings persistence."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QTabWidget

from fontplayground.catalog.cache import CatalogCache
from fontplayground.engine.spec import ForgeSpec
from fontplayground.paths import config_dir, default_font_dirs
from fontplayground.ui.fonts_tab import FontsTab
from fontplayground.ui.forge_tab import ForgeTab, clean_stale_results
from fontplayground.ui.preview import PreviewWidget
from fontplayground.ui.workers import ScanWorker

COMBINE_WAIT_MS = 180_000   # closing waits this long for a cancelled combine to reach its next stage boundary
SCAN_WAIT_MS = 3_000        # closing waits this long for an interrupted scan to stop
QUIT_QUESTION = "A combine is still running. Quit anyway?"


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
        self.font_dirs = [Path(d) for d in font_dirs]
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache = CatalogCache(self.config_dir / "catalog.json")
        self.cache.load()
        self.settings_path = self.config_dir / "settings.json"
        self.forge_settings_path = self.config_dir / "forge_last.json"
        self._settings = _read_json(self.settings_path, {"extra_dirs": []})
        self._pending_restore = _read_json(self.forge_settings_path, None)
        self.scan_worker: ScanWorker | None = None
        self._pending_scan: bool | None = None   # use_cache of a scan requested while another was running
        self._closing = False
        self._forge_status = ""                  # what the forge tab last put in the status bar
        clean_stale_results()                    # results of runs that did not get to discard them

        self.fonts_preview = PreviewWidget()
        self.forge_preview = PreviewWidget()
        self.fonts_tab = FontsTab(self.fonts_preview)
        self.forge_tab = ForgeTab(self.forge_preview)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.fonts_tab, "Fonts")
        self.tabs.addTab(self.forge_tab, "Forge")
        self.setCentralWidget(self.tabs)
        self.statusBar()

        self.fonts_preview.sampleChanged.connect(self.forge_preview.set_sample_text)
        self.forge_preview.sampleChanged.connect(self.fonts_preview.set_sample_text)
        self.fonts_tab.selectionChanged.connect(self._on_selection_changed)
        self.fonts_tab.goToForge.connect(lambda: self.tabs.setCurrentIndex(1))
        self.fonts_tab.rescanRequested.connect(lambda: self.start_scan(use_cache=False))
        self.fonts_tab.addFolderRequested.connect(self.add_folder)
        self.forge_tab.settingsChanged.connect(self.save_forge_settings)
        self.forge_tab.materialRemoved.connect(self._on_material_removed)
        self.forge_tab.statusMessage.connect(self._on_forge_status)
        self.forge_tab.busyChanged.connect(self._on_forge_busy)

        self.start_scan(use_cache=True)

    # ----- scanning -----
    def all_dirs(self) -> list[Path]:
        return self.font_dirs + [Path(d) for d in self._settings.get("extra_dirs", [])]

    def start_scan(self, use_cache: bool) -> None:
        if self.scan_worker is not None and self.scan_worker.isRunning():
            # Remember the request; _on_scan_finished starts it. A no-cache request wins over a cached one.
            self._pending_scan = use_cache if self._pending_scan is None else (self._pending_scan and use_cache)
            return
        self.fonts_tab.begin_scan()
        self.statusBar().showMessage("Scanning fonts…")
        self.scan_worker = ScanWorker(self.all_dirs(), self.cache, use_cache, parent=self)
        self.scan_worker.face_found.connect(self.fonts_tab.add_face)
        self.scan_worker.progress.connect(self.fonts_tab.set_progress)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, result) -> None:
        if self._closing or (self.scan_worker is not None and self.scan_worker.interrupted):
            return  # a partial catalog: leave the ticks and the saved forge settings alone
        self.fonts_tab.end_scan(result)
        msg = f"{len(result.faces)} font faces found"
        if result.failed:
            msg += f", {len(result.failed)} unreadable files skipped"
        self.statusBar().showMessage(msg, 10000)
        if self._pending_restore:
            faces = self.fonts_tab.faces_by_key()
            spec = ForgeSpec.from_dict(self._pending_restore, faces)
            self.fonts_tab.set_ticked([m.face.key for m in spec.materials])
            self.forge_tab.from_settings(self._pending_restore, faces)
            self._pending_restore = None
        if self._pending_scan is not None:
            use_cache, self._pending_scan = self._pending_scan, None
            if self.scan_worker is not None:
                self.scan_worker.wait()  # run() has returned; let the thread exit so start_scan sees it idle
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

    # ----- forge wiring -----
    def _on_selection_changed(self, faces: list) -> None:
        self.forge_tab.set_materials(faces)
        self.save_forge_settings()

    def _on_material_removed(self, key) -> None:
        keys = [f.key for f in self.fonts_tab.selected_faces() if f.key != key]
        self.fonts_tab.set_ticked(keys)

    def _on_forge_status(self, text: str) -> None:
        """Show the forge tab's validation error; clear it again only if it is still what the bar shows."""
        bar = self.statusBar()
        if text:
            bar.showMessage(text)
        elif bar.currentMessage() == self._forge_status:
            bar.clearMessage()
        self._forge_status = text

    def _on_forge_busy(self, busy: bool) -> None:
        self.fonts_tab.tree.setEnabled(not busy)  # ticks would change the materials under a running combine

    def save_forge_settings(self) -> None:
        _write_json(self.forge_settings_path, self.forge_tab.to_settings())

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.forge_tab.is_busy():
            answer = QMessageBox.question(self, "Combine running", QUIT_QUESTION)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.forge_tab.cancel_combine(wait_ms=COMBINE_WAIT_MS)
        self._closing = True
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.interrupt()
            self.scan_worker.wait(SCAN_WAIT_MS)
        self.forge_tab.discard_result()
        super().closeEvent(event)


def main() -> None:
    logging.getLogger("fontTools").setLevel(logging.ERROR)  # timestamp/version warnings are noise here
    app = QApplication(sys.argv)
    app.setApplicationName("Font Playground")
    window = MainWindow(default_font_dirs(), config_dir())
    window.resize(1280, 820)
    window.show()
    sys.exit(app.exec())
