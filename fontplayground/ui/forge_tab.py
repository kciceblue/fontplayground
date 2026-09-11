"""Forge tab: materials in priority order, script rules, defaults/output, preview and report."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace, read_faces
from fontplayground.engine.scripts import GROUPS
from fontplayground.engine.spec import ForgeSpec, MaterialSpec
from fontplayground.ui.preview import PreviewWidget, font_loader
from fontplayground.ui.workers import CombineWorker

FaceKey = tuple[str, int]

MATERIAL_COLUMNS = ["#", "Font", "Weight", "Scale %", "Base", "Note"]
COL_NUM, COL_FONT, COL_WEIGHT, COL_SCALE, COL_BASE, COL_NOTE = range(6)
AUTO_RULE = "Auto (priority order)"
AS_IS = "As is"
DEFAULT_WEIGHTS = [str(w) for w in range(100, 950, 50)]
RESULT_DIR = Path(tempfile.gettempdir()) / "fontplayground"   # combine results live here until saved or discarded
RESULT_GLOB = "forged-*.ttf"


def clean_stale_results() -> None:
    """Delete results left behind by earlier runs (a crash, or a quit while a combine was still running)."""
    try:
        stale = list(RESULT_DIR.glob(RESULT_GLOB))
    except OSError:
        return
    for path in stale:
        try:
            path.unlink()
        except OSError:
            pass


@dataclass
class MaterialRow:
    face: FontFace
    weight: int | None = None
    scale: float | None = None


def _note_for(face: FontFace) -> str:
    notes = []
    if face.unsupported_reason:
        notes.append(face.unsupported_reason)
    if face.embedding == "restricted":
        notes.append("restricted licence")
    if not face.has_wght_axis and not face.is_variable:
        notes.append("static font: extra weight will be synthetic")
    return "; ".join(notes)


class ForgeTab(QWidget):
    settingsChanged = Signal()          # any change to rows, rules, defaults, output path
    materialRemoved = Signal(object)    # face.key removed via the Remove button
    statusMessage = Signal(str)         # first validation error of the current spec, "" when it is valid
    busyChanged = Signal(bool)          # a combine started (True) or ended (False)

    def __init__(self, preview: PreviewWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preview = preview
        self._rows: list[MaterialRow] = []
        self._base_index = 0
        self._rules: dict[str, FaceKey | None] = {g.id: None for g in GROUPS}
        self._base_group: QButtonGroup | None = None
        self._busy = False
        self._validation_error = ""
        self.result_path: str | None = None
        self.worker: CombineWorker | None = None

        grid = QGridLayout(self)
        grid.addWidget(self._build_materials_box(), 0, 0)
        grid.addWidget(self._build_rules_box(), 1, 0)
        grid.addWidget(self._build_defaults_box(), 0, 1)
        grid.addWidget(self._build_preview_box(), 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        self._rebuild_table()
        self._rebuild_rules()
        self._set_busy(False)
        self._revalidate()

    # ----- construction -----
    def _build_materials_box(self) -> QGroupBox:
        box = self.materials_box = QGroupBox("Materials")
        layout = QVBoxLayout(box)
        self.table = QTableWidget(0, len(MATERIAL_COLUMNS))
        self.table.setHorizontalHeaderLabels(MATERIAL_COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_FONT, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        self.remove_button = QPushButton("Remove")
        self.up_button.clicked.connect(lambda: self._move_current(-1))
        self.down_button.clicked.connect(lambda: self._move_current(1))
        self.remove_button.clicked.connect(self._remove_current)
        for b in (self.up_button, self.down_button, self.remove_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def _build_rules_box(self) -> QGroupBox:
        box = self.rules_box = QGroupBox("Script rules")
        layout = QVBoxLayout(box)
        self.rules_table = QTableWidget(len(GROUPS), 2)
        self.rules_table.setHorizontalHeaderLabels(["Script", "Material"])
        self.rules_table.verticalHeader().hide()
        self.rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rules_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.rules_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, group in enumerate(GROUPS):
            item = QTableWidgetItem(group.label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.rules_table.setItem(row, 0, item)
        layout.addWidget(self.rules_table)
        return box

    def _build_defaults_box(self) -> QGroupBox:
        box = self.defaults_box = QGroupBox("Defaults and output")
        layout = QVBoxLayout(box)
        form = QFormLayout()
        self.family_edit = QLineEdit("Forged")
        self.style_edit = QLineEdit("Regular")
        self.default_weight_combo = QComboBox()
        self.default_weight_combo.addItems([AS_IS] + DEFAULT_WEIGHTS)
        self.default_scale_spin = QSpinBox()
        self.default_scale_spin.setRange(10, 1000)
        self.default_scale_spin.setSuffix(" %")
        self.default_scale_spin.setValue(100)
        self.output_edit = QLineEdit(str(Path.home() / "Documents" / "Forged-Regular.ttf"))
        self.browse_button = QPushButton("Browse…")
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.browse_button)
        form.addRow("Family name", self.family_edit)
        form.addRow("Style name", self.style_edit)
        form.addRow("Default weight", self.default_weight_combo)
        form.addRow("Default scale", self.default_scale_spin)
        form.addRow("Output file", output_row)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.combine_button = QPushButton("Combine")
        self.save_button = QPushButton("Save…")
        self.save_button.setEnabled(False)
        actions.addWidget(self.combine_button)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.stage_label = QLabel("")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stage_label)
        layout.addStretch(1)

        self.family_edit.textChanged.connect(self._emit_changed)
        self.style_edit.textChanged.connect(self._emit_changed)
        self.default_weight_combo.currentIndexChanged.connect(self._emit_changed)
        self.default_scale_spin.valueChanged.connect(self._emit_changed)
        self.output_edit.textChanged.connect(self._emit_changed)
        self.browse_button.clicked.connect(self._browse_output)
        self.combine_button.clicked.connect(self.combine)
        self.save_button.clicked.connect(self._save)
        return box

    def _build_preview_box(self) -> QGroupBox:
        box = self.preview_box = QGroupBox("Preview and report")
        layout = QVBoxLayout(box)
        layout.addWidget(self.preview, 2)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("Combine to see the report")
        layout.addWidget(self.report, 1)
        return box

    # ----- public API -----
    def rows(self) -> list[MaterialRow]:
        return list(self._rows)

    def set_materials(self, faces: list[FontFace]) -> None:
        by_key: dict[FaceKey, FontFace] = {}
        for f in faces:
            by_key.setdefault(f.key, f)
        old_keys = [r.face.key for r in self._rows]
        base_key = self._base_key()
        kept = [MaterialRow(by_key[r.face.key], r.weight, r.scale) for r in self._rows if r.face.key in by_key]
        kept_keys = {r.face.key for r in kept}
        self._rows = kept + [MaterialRow(f) for k, f in by_key.items() if k not in kept_keys]
        self._base_index = self._index_of(base_key)
        self._rules = {g: (k if k in by_key else None) for g, k in self._rules.items()}
        self._refresh()
        if [r.face.key for r in self._rows] != old_keys:
            self._emit_changed()
        else:
            self._revalidate()  # the faces themselves may have changed (rescan), so re-check anyway

    def build_spec(self) -> ForgeSpec:
        index_of = {r.face.key: i for i, r in enumerate(self._rows)}
        rules = {g: (index_of.get(k) if k is not None else None) for g, k in self._rules.items()}
        weight_text = self.default_weight_combo.currentText()
        return ForgeSpec(
            materials=[MaterialSpec(r.face, r.weight, r.scale) for r in self._rows],
            base_index=self._base_index if 0 <= self._base_index < len(self._rows) else 0,
            script_rules=rules,
            default_weight=None if weight_text == AS_IS else int(weight_text),
            default_scale=self.default_scale_spin.value() / 100,
            family_name=self.family_edit.text(),
            style_name=self.style_edit.text(),
        )

    def apply_spec(self, spec: ForgeSpec) -> None:
        self._rows = [MaterialRow(m.face, m.weight, m.scale) for m in spec.materials]
        self._base_index = spec.base_index if 0 <= spec.base_index < len(self._rows) else 0
        self._rules = {g.id: None for g in GROUPS}
        for g, idx in spec.script_rules.items():
            if idx is not None and 0 <= idx < len(self._rows):
                self._rules[g] = self._rows[idx].face.key
            elif g in self._rules:
                self._rules[g] = None
        for w in (self.family_edit, self.style_edit, self.default_weight_combo, self.default_scale_spin):
            w.blockSignals(True)
        try:
            self.family_edit.setText(spec.family_name)
            self.style_edit.setText(spec.style_name)
            i = self.default_weight_combo.findText(str(spec.default_weight)) if spec.default_weight is not None else 0
            self.default_weight_combo.setCurrentIndex(max(i, 0))
            self.default_scale_spin.setValue(round(spec.default_scale * 100))
        finally:
            for w in (self.family_edit, self.style_edit, self.default_weight_combo, self.default_scale_spin):
                w.blockSignals(False)
        self._refresh()
        self._emit_changed()

    def to_settings(self) -> dict:
        d = self.build_spec().to_dict()
        d["output_path"] = self.output_edit.text()
        return d

    def from_settings(self, d: dict, faces_by_key: dict[FaceKey, FontFace]) -> None:
        output = d.get("output_path")
        if output:
            self.output_edit.blockSignals(True)
            self.output_edit.setText(str(output))
            self.output_edit.blockSignals(False)
        self.apply_spec(ForgeSpec.from_dict(d, faces_by_key))

    def validation_error(self) -> str:
        """The first problem with the current spec (also the Combine button's tooltip), or "" when it is valid."""
        return self._validation_error

    def is_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def combine(self) -> None:
        if self.is_busy():
            return
        spec = self.build_spec()
        errors = spec.validate()
        if errors:  # the button is disabled in this state; this covers programmatic calls
            QMessageBox.warning(self, "Cannot combine", "\n".join(errors))
            return
        self.discard_result()
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULT_DIR / f"forged-{uuid4().hex[:8]}.ttf"
        self._set_busy(True)
        self.progress_bar.setValue(0)
        self.stage_label.setText("Starting…")
        self.worker = CombineWorker(spec, str(out))
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def cancel_combine(self, wait_ms: int | None = None) -> bool:
        """Ask a running combine to stop at its next stage boundary; optionally block until it has.

        Returns True when there was a combine to cancel. The worker then emits `cancelled` (not `failed`).
        """
        if not self.is_busy():
            return False
        self.worker.cancel()
        if wait_ms is not None:
            self.worker.wait(wait_ms)
        return True

    def save_to(self, path: str) -> None:
        if not self.result_path or not Path(self.result_path).is_file():
            raise RuntimeError("Nothing to save")
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.result_path, dest)

    def discard_result(self) -> None:
        """Forget the last result: unload it from Qt and delete its temp file."""
        if self.result_path is None:
            return
        path, self.result_path = self.result_path, None
        try:
            font_loader().unload(path)
        except Exception:
            pass
        try:
            Path(path).unlink()
        except OSError:
            pass
        self.preview.clear()
        self.save_button.setEnabled(False)

    # ----- cell-widget accessors (handy for tests and the app) -----
    def weight_spin(self, row: int) -> QSpinBox:
        return self.table.cellWidget(row, COL_WEIGHT)

    def scale_spin(self, row: int) -> QSpinBox:
        return self.table.cellWidget(row, COL_SCALE)

    def base_radio(self, row: int) -> QRadioButton:
        return self.table.cellWidget(row, COL_BASE)

    def rule_combo(self, group_id: str) -> QComboBox:
        row = next(i for i, g in enumerate(GROUPS) if g.id == group_id)
        return self.rules_table.cellWidget(row, 1)

    # ----- table building -----
    def _refresh(self, select: int | None = None) -> None:
        self._rebuild_table()
        self._rebuild_rules()
        if select is not None and 0 <= select < self.table.rowCount():
            self.table.selectRow(select)

    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        if self._base_group is not None:
            self._base_group.deleteLater()
        self._base_group = QButtonGroup(self)
        self._base_group.setExclusive(True)
        if not 0 <= self._base_index < len(self._rows):
            self._base_index = 0
        self.table.setRowCount(len(self._rows))
        for i, row in enumerate(self._rows):
            self.table.setItem(i, COL_NUM, QTableWidgetItem(str(i + 1)))
            font_item = QTableWidgetItem(row.face.display_name)
            font_item.setToolTip(f"{row.face.display_name}\n{row.face.path} (face {row.face.index})")
            self.table.setItem(i, COL_FONT, font_item)

            weight = QSpinBox()
            weight.setRange(0, 1000)
            weight.setSingleStep(50)
            weight.setSpecialValueText("default")
            weight.setValue(row.weight or 0)
            weight.valueChanged.connect(lambda v, i=i: self._on_weight_changed(i, v))
            self.table.setCellWidget(i, COL_WEIGHT, weight)

            scale = QSpinBox()
            scale.setRange(0, 1000)
            scale.setSuffix(" %")
            scale.setSpecialValueText("default")
            scale.setValue(round(row.scale * 100) if row.scale is not None else 0)
            scale.valueChanged.connect(lambda v, i=i: self._on_scale_changed(i, v))
            self.table.setCellWidget(i, COL_SCALE, scale)

            radio = QRadioButton()
            radio.setChecked(i == self._base_index)
            self._base_group.addButton(radio, i)
            self.table.setCellWidget(i, COL_BASE, radio)

            note_item = QTableWidgetItem(_note_for(row.face))
            note_item.setToolTip(note_item.text())  # the column elides long notes
            self.table.setItem(i, COL_NOTE, note_item)
        self._base_group.idToggled.connect(self._on_base_toggled)
        has_rows = bool(self._rows)
        for b in (self.up_button, self.down_button, self.remove_button):
            b.setEnabled(has_rows)

    def _rebuild_rules(self) -> None:
        index_of = {r.face.key: i for i, r in enumerate(self._rows)}
        items = [AUTO_RULE] + [f"{i + 1}. {r.face.display_name}" for i, r in enumerate(self._rows)]
        for row, group in enumerate(GROUPS):
            combo = QComboBox()
            combo.addItems(items)
            key = self._rules.get(group.id)
            idx = index_of.get(key) if key is not None else None
            combo.setCurrentIndex(idx + 1 if idx is not None else 0)
            combo.currentIndexChanged.connect(lambda index, g=group.id: self._on_rule_changed(g, index))
            self.rules_table.setCellWidget(row, 1, combo)

    # ----- row bookkeeping -----
    def _base_key(self) -> FaceKey | None:
        return self._rows[self._base_index].face.key if 0 <= self._base_index < len(self._rows) else None

    def _index_of(self, key: FaceKey | None) -> int:
        return next((i for i, r in enumerate(self._rows) if r.face.key == key), 0)

    def _current_row(self) -> int:
        row = self.table.currentRow()
        if row < 0:
            selected = self.table.selectionModel().selectedRows()
            row = selected[0].row() if selected else -1
        return row

    def _move_current(self, delta: int) -> None:
        row = self._current_row()
        new = row + delta
        if row < 0 or not 0 <= new < len(self._rows):
            return
        base_key = self._base_key()
        self._rows[row], self._rows[new] = self._rows[new], self._rows[row]
        self._base_index = self._index_of(base_key)
        self._refresh(select=new)
        self._emit_changed()

    def _remove_current(self) -> None:
        row = self._current_row()
        if not 0 <= row < len(self._rows):
            return
        base_key = self._base_key()
        removed = self._rows.pop(row)
        self._base_index = self._index_of(base_key)
        self._rules = {g: (None if k == removed.face.key else k) for g, k in self._rules.items()}
        self._refresh(select=min(row, len(self._rows) - 1))
        self.materialRemoved.emit(removed.face.key)
        self._emit_changed()

    def _on_weight_changed(self, row: int, value: int) -> None:
        if 0 <= row < len(self._rows):
            self._rows[row].weight = value or None
            self._emit_changed()

    def _on_scale_changed(self, row: int, value: int) -> None:
        if 0 <= row < len(self._rows):
            self._rows[row].scale = value / 100 if value else None
            self._emit_changed()

    def _on_base_toggled(self, row: int, checked: bool) -> None:
        if checked and 0 <= row < len(self._rows) and row != self._base_index:
            self._base_index = row
            self._emit_changed()

    def _on_rule_changed(self, group_id: str, index: int) -> None:
        key = self._rows[index - 1].face.key if 0 < index <= len(self._rows) else None
        if self._rules.get(group_id) != key:
            self._rules[group_id] = key
            self._emit_changed()

    def _emit_changed(self, *_args) -> None:
        """Every edit goes through here: re-check the spec (Combine button, status text), then tell the app."""
        self._revalidate()
        self.settingsChanged.emit()

    def _revalidate(self) -> None:
        errors = self.build_spec().validate()
        self._validation_error = errors[0] if errors else ""
        self._update_combine_button()
        self.statusMessage.emit(self._validation_error)

    def _update_combine_button(self) -> None:
        self.combine_button.setEnabled(not self._busy and not self._validation_error)
        self.combine_button.setToolTip(self._validation_error)

    # ----- output / combine / save -----
    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Output font", self.output_edit.text(), "TrueType font (*.ttf)")
        if path:
            self.output_edit.setText(path)

    def _set_busy(self, busy: bool) -> None:
        """While a combine runs, the inputs are frozen; the preview editor and the report stay usable."""
        changed = busy != self._busy
        self._busy = busy
        for box in (self.materials_box, self.rules_box, self.defaults_box):
            box.setEnabled(not busy)
        self._update_combine_button()
        self.progress_bar.setVisible(busy)
        self.stage_label.setVisible(busy)
        if changed:
            self.busyChanged.emit(busy)

    def _on_progress(self, stage: str, fraction: float) -> None:
        self.progress_bar.setValue(int(fraction * 100))
        self.stage_label.setText(stage)

    def _on_succeeded(self, report) -> None:
        self.result_path = report.output_path
        text = report.as_text()
        try:
            self.preview.set_face(read_faces(self.result_path)[0])
        except Exception as e:  # the file exists but Qt/fontTools could not read it back
            text += f"\n\nPreview unavailable: {e}"
        missing = self.preview.missing_characters()
        if missing:
            text += "\nSample characters not covered: " + " ".join(missing)
        self.report.setPlainText(text)
        self.save_button.setEnabled(True)
        self._set_busy(False)

    def _on_failed(self, message: str) -> None:
        self.report.setPlainText("Combine failed:\n" + message)
        self._set_busy(False)
        first_line = message.strip().splitlines()[0] if message.strip() else "Unknown error"
        QMessageBox.critical(self, "Combine failed", first_line)

    def _on_cancelled(self) -> None:
        if self.worker is not None:  # the file may exist if the cancel landed between "finish" and "verify"
            try:
                Path(self.worker.output_path).unlink()
            except OSError:
                pass
        self.report.setPlainText("Combine cancelled.")
        self._set_busy(False)

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save font", self.output_edit.text(), "TrueType font (*.ttf)")
        if not path:
            return
        try:
            self.save_to(path)
        except (RuntimeError, OSError) as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self.output_edit.setText(path)
        answer = QMessageBox.question(self, "Saved", f"Saved to {path}\n\nOpen the folder?")
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
