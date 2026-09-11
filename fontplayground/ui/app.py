"""Main window: Fonts tab + Forge tab, scanning, and settings persistence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QTabWidget

from fontplayground.catalog.cache import CatalogCache
from fontplayground.engine.spec import ForgeSpec
from fontplayground.paths import config_dir, default_font_dirs
from fontplayground.ui.fonts_tab import FontsTab
from fontplayground.ui.forge_tab import ForgeTab
from fontplayground.ui.preview import PreviewWidget
from fontplayground.ui.workers import ScanWorker


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

        self.start_scan(use_cache=True)

    # ----- scanning -----
    def all_dirs(self) -> list[Path]:
        return self.font_dirs + [Path(d) for d in self._settings.get("extra_dirs", [])]

    def start_scan(self, use_cache: bool) -> None:
        if self.scan_worker is not None and self.scan_worker.isRunning():
            return
        self.fonts_tab.begin_scan()
        self.statusBar().showMessage("Scanning fonts…")
        self.scan_worker = ScanWorker(self.all_dirs(), self.cache, use_cache, parent=self)
        self.scan_worker.face_found.connect(self.fonts_tab.add_face)
        self.scan_worker.progress.connect(self.fonts_tab.set_progress)
        self.scan_worker.finished_scan.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, result) -> None:
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

    def save_forge_settings(self) -> None:
        _write_json(self.forge_settings_path, self.forge_tab.to_settings())

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.requestInterruption()
            self.scan_worker.wait(3000)
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Font Playground")
    window = MainWindow(default_font_dirs(), config_dir())
    window.resize(1280, 820)
    window.show()
    sys.exit(app.exec())
