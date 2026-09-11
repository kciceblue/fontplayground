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
        self.interrupted = False  # sticky, unlike isInterruptionRequested(), which is False again once the thread ends

    def interrupt(self) -> None:
        """Stop after the current file. The ScanResult emitted afterwards is partial; `interrupted` says so."""
        self.interrupted = True
        self.requestInterruption()

    def _should_stop(self) -> bool:
        return self.interrupted or self.isInterruptionRequested()

    def run(self) -> None:
        result = scan(self.dirs, self.cache, on_face=self.face_found.emit, on_progress=self.progress.emit,
                      use_cache=self.use_cache, should_stop=self._should_stop)
        self.finished_scan.emit(result)


class CombineWorker(QThread):
    progress = Signal(str, float)
    succeeded = Signal(object)  # ForgeReport
    failed = Signal(str)        # first line: the error; the rest: the full traceback
    cancelled = Signal()        # cancel() was honoured; nothing else is emitted for this run

    def __init__(self, spec: ForgeSpec, output_path: str, parent=None) -> None:
        super().__init__(parent)
        self.spec, self.output_path = spec, output_path
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the run to stop. forge() reports progress between stages, so it stops at the next stage boundary."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _report_progress(self, stage: str, fraction: float) -> None:
        if self._cancelled:
            raise ForgeError("cancelled", None, "Combine cancelled")
        self.progress.emit(stage, fraction)

    def run(self) -> None:
        try:
            report = forge(self.spec, self.output_path, progress=self._report_progress)
        except ForgeError as e:
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(f"{e}\n\n{traceback.format_exc()}")
            return
        except Exception as e:  # keep the GUI alive on unexpected errors
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.failed.emit(f"Unexpected error: {e}\n\n{traceback.format_exc()}")
            return
        self.succeeded.emit(report)
