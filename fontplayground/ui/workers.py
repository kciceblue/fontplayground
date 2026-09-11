"""QThread wrappers around the scanner and the forge."""
from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from fontplayground.catalog.cache import CatalogCache
from fontplayground.catalog.scanner import scan
from fontplayground.engine.forge import forge
from fontplayground.engine.spec import ForgeError, ForgeSpec


class ScanWorker(QThread):
    face_found = Signal(object)      # FontFace
    progress = Signal(int, int)      # done, total
    finished_scan = Signal(object)   # ScanResult

    def __init__(self, dirs: list[Path], cache: CatalogCache | None, use_cache: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.dirs, self.cache, self.use_cache = list(dirs), cache, use_cache

    def run(self) -> None:
        result = scan(self.dirs, self.cache, on_face=self.face_found.emit, on_progress=self.progress.emit,
                      use_cache=self.use_cache, should_stop=self.isInterruptionRequested)
        self.finished_scan.emit(result)


class CombineWorker(QThread):
    progress = Signal(str, float)
    succeeded = Signal(object)  # ForgeReport
    failed = Signal(str)

    def __init__(self, spec: ForgeSpec, output_path: str, parent=None) -> None:
        super().__init__(parent)
        self.spec, self.output_path = spec, output_path

    def run(self) -> None:
        try:
            self.succeeded.emit(forge(self.spec, self.output_path, progress=self.progress.emit))
        except ForgeError as e:
            self.failed.emit(str(e))
        except Exception as e:  # keep the GUI alive on unexpected errors
            self.failed.emit(f"Unexpected error: {e}\n\n{traceback.format_exc()}")
