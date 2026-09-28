"""The Advanced dialog: who draws which script, line spacing, defaults, and the report of the last build.

"Who draws what" lists the script groups some font covers (all fifteen on request) with a "Drawn by" combo —
"Auto → <the font the app would pick>" or a font the user pins — and how many characters of the group each font
has, the drawing font first. Below: which font the line spacing comes from, the boldness and size for fonts
without their own, and the last build's report (or its error). Non-modal; the app keeps one instance. Everything
shown comes from the ForgeModel and the build controller; every choice goes back to the model. While a build runs
the app locks the dialog (set_locked).
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace
from fontplayground.engine.scripts import GROUP_IDS, GROUPS, LABELS
from fontplayground.ui import smart
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.recipe import SCALE_RANGE, fill_weight_combo, scale_percent, select_weight
from fontplayground.ui.theme import LIGHT, Theme

FaceKey = tuple[str, int]

TITLE_TEXT = "Advanced"
WHO_TITLE = "Who draws what"
TABLE_COLUMNS = ["Script", "Drawn by", "Characters"]
COL_SCRIPT, COL_DRAWN_BY, COL_COUNTS = range(3)
AUTO_PREFIX = "Auto → "
NOBODY, NO_COUNT = "nobody", "—"
SHOW_ALL_TEXT = f"Show all {len(GROUPS)} scripts"
SHOW_COVERED_TEXT = "Show only covered scripts"
MAIN_CHOICE = "Main font"             # first entry of "Line spacing from": the base follows the main font
DEFAULTS_NOTE = "For fonts without their own setting."
BUILD_TITLE = "Last build"
NO_BUILD_TEXT = "No build yet."

STYLE = """
QDialog#advanced { background: $window; }
QLabel { color: $text; background: transparent; }
QLabel#sectionTitle { font-size: 14px; font-weight: 600; }
QLabel#fieldLabel { color: $text_secondary; }
QLabel#muted { color: $muted; }
QTableWidget#suppliers { background: $surface; color: $text; border: 1px solid $border_soft; border-radius: 6px;
                         gridline-color: $border_soft; }
QTableWidget#suppliers QHeaderView::section { background: $surface_alt; color: $text_secondary; border: none;
                                              border-bottom: 1px solid $border_soft; padding: 4px 6px; }
QPushButton#showAll { border: 1px solid $border; border-radius: 6px; background: transparent; padding: 4px 10px;
                      color: $text_secondary; }
QPushButton#showAll:hover, QPushButton#showAll:checked { border-color: $accent; color: $accent; }
QComboBox, QSpinBox { background: $surface; color: $text; border: 1px solid $border; border-radius: 6px;
                      padding: 3px 8px; }
QComboBox:disabled, QSpinBox:disabled { color: $faint; border-color: $border_soft; }
QTableWidget#suppliers QComboBox { border: none; border-radius: 0; background: transparent; }
QPushButton#closeButton { background: transparent; color: $text; border: 1px solid $border; border-radius: 8px;
                          padding: 6px 18px; }
QPushButton#closeButton:hover { border-color: $accent; color: $accent; }
QPlainTextEdit#report { background: $surface_sunken; color: $text_secondary; border: 1px solid $border_soft;
                        border-radius: 6px; padding: 4px; }
"""


def short_names(faces: Iterable[FontFace]) -> dict[FaceKey, str]:
    """The family name when it identifies the font on its own, else 'Family Style'."""
    faces = list(faces)
    families = [f.family for f in faces]
    return {f.key: (f.family if families.count(f.family) == 1 else f.display_name) for f in faces}


def _item(text: str, colour: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if colour is None:
        item.setToolTip(text)
    else:
        item.setForeground(QBrush(QColor(colour)))
    return item


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


class AdvancedDialog(QDialog):
    """Who draws what, line spacing, defaults and the last build's report; non-modal."""

    def __init__(self, model: ForgeModel, controller: QObject, parent: QWidget | None = None,
                 theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.model = model
        self.controller = controller      # anything with a `changed` signal, `report` and `error_detail`
        self._table_groups: list[str] = []
        self._locked = False
        self._theme = theme
        self.setObjectName("advanced")
        self.setWindowTitle(TITLE_TEXT)
        self.setModal(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(8)

        # ----- who draws what -----
        self.who_title = _section(WHO_TITLE)
        layout.addWidget(self.who_title)
        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setObjectName("suppliers")
        self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_SCRIPT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_DRAWN_BY, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_COUNTS, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 4)
        self.show_all_button = QPushButton(SHOW_ALL_TEXT)
        self.show_all_button.setObjectName("showAll")
        self.show_all_button.setCheckable(True)
        self.show_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_all_button.setToolTip("Also list the scripts none of your fonts draws")
        layout.addWidget(self.show_all_button, 0, Qt.AlignmentFlag.AlignLeft)

        # ----- line spacing and defaults -----
        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setHorizontalSpacing(12)
        self.base_combo = QComboBox()
        self.base_combo.setToolTip("Which font's line spacing your font uses (the main font's unless you choose)")
        self.default_weight_combo = QComboBox()
        fill_weight_combo(self.default_weight_combo)
        self.default_weight_combo.setToolTip("Boldness of every font that has no Weight of its own")
        self.default_scale_spin = QSpinBox()
        self.default_scale_spin.setRange(*SCALE_RANGE)
        self.default_scale_spin.setSuffix(" %")
        self.default_scale_spin.setValue(100)
        self.default_scale_spin.setKeyboardTracking(False)
        self.default_scale_spin.setToolTip("Size of every font that has no Size of its own")
        self.defaults_note = QLabel(DEFAULTS_NOTE)
        self.defaults_note.setObjectName("muted")
        defaults = QHBoxLayout()
        defaults.setSpacing(8)
        defaults.addWidget(self.default_scale_spin)
        defaults.addStretch(1)
        form.addRow(self._field_label("Line spacing from"), self.base_combo)
        form.addRow(self._field_label("Default boldness"), self.default_weight_combo)
        form.addRow(self._field_label("Default size"), defaults)
        form.addRow("", self.defaults_note)
        layout.addLayout(form)

        # ----- last build -----
        self.build_title = _section(BUILD_TITLE)
        layout.addSpacing(6)
        layout.addWidget(self.build_title)
        self.report_text = QPlainTextEdit()
        self.report_text.setObjectName("report")
        self.report_text.setReadOnly(True)
        self.report_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.report_text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_button.setObjectName("closeButton")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        # ----- wiring (bound methods: Qt drops them cleanly if the dialog dies before the model) -----
        self.show_all_button.toggled.connect(self._on_show_all_toggled)
        self.base_combo.currentIndexChanged.connect(self._on_base_chosen)
        self.default_weight_combo.currentIndexChanged.connect(self._on_defaults_edited)
        self.default_scale_spin.valueChanged.connect(self._on_defaults_edited)
        self.model.materialsChanged.connect(self.refresh)
        self.controller.changed.connect(self._refresh_report)
        self.setStyleSheet(theme.render(STYLE))
        self.resize(640, 720)
        self.refresh()
        self._refresh_report()

    # ----- public API -----
    def refresh(self) -> None:
        """Rebuild the table, line spacing and defaults from the model."""
        self._refresh_settings()
        self._rebuild_table()

    def table_groups(self) -> list[str]:
        """Group ids listed in the table, top to bottom."""
        return list(self._table_groups)

    def table_row(self, group_id: str) -> int | None:
        return self._table_groups.index(group_id) if group_id in self._table_groups else None

    def supplier_combo(self, group_id: str) -> QComboBox | None:
        """The 'Drawn by' combo of a covered group (None for a group nobody covers or one not listed)."""
        row = self.table_row(group_id)
        widget = self.table.cellWidget(row, COL_DRAWN_BY) if row is not None else None
        return widget if isinstance(widget, QComboBox) else None

    def cell_text(self, group_id: str, column: int) -> str:
        """What a cell shows: an item's text, or the current text of the 'Drawn by' combo."""
        row = self.table_row(group_id)
        if row is None:
            return ""
        combo = self.supplier_combo(group_id) if column == COL_DRAWN_BY else None
        if combo is not None:
            return combo.currentText()
        item = self.table.item(row, column)
        return item.text() if item is not None else ""

    def set_locked(self, locked: bool) -> None:
        """While a build runs nothing here may change the font: the 'Drawn by' combos, line spacing and defaults
        are disabled. Show all and the report stay usable (they change nothing)."""
        self._locked = bool(locked)
        self._apply_enabled()
        for g in self._table_groups:
            combo = self.supplier_combo(g)
            if combo is not None:
                combo.setEnabled(not self._locked)

    def is_locked(self) -> bool:
        return self._locked

    def apply_theme(self, theme: Theme) -> None:
        """Re-render the sheet and the table (its muted cells take their colour from the theme)."""
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        self._rebuild_table()

    # ----- model -> widgets -----
    def _refresh_settings(self) -> None:
        rows = self.model.rows
        base_index = self.model.index_of(self.model.base_key) if self.model.base_key is not None else None
        widgets = (self.base_combo, self.default_weight_combo, self.default_scale_spin)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.base_combo.clear()
            self.base_combo.addItem(MAIN_CHOICE)
            for row in rows:
                self.base_combo.addItem(row.face.display_name)
            self.base_combo.setCurrentIndex(base_index + 1 if base_index is not None else 0)
            select_weight(self.default_weight_combo, self.model.default_weight)
            percent = scale_percent(self.model.default_scale)
            if self.default_scale_spin.value() != percent:
                self.default_scale_spin.setValue(percent)
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._apply_enabled()

    def _apply_enabled(self) -> None:
        self.base_combo.setEnabled(bool(self.model.rows) and not self._locked)
        self.default_weight_combo.setEnabled(not self._locked)
        self.default_scale_spin.setEnabled(not self._locked)

    def _rebuild_table(self) -> None:
        faces = [r.face for r in self.model.rows]
        keys = [f.key for f in faces]
        counts = smart.group_counts(faces)
        covered = [g for g in GROUP_IDS if any(counts[k][g] for k in keys)]
        shown = list(GROUP_IDS) if self.show_all_button.isChecked() else covered
        rules = self.model.script_rules() if keys else {}
        pins = self.model.pins
        names = short_names(faces)
        display = {f.key: f.display_name for f in faces}
        self._table_groups = shown
        self.table.setRowCount(0)      # drops the old combos (Qt deletes them later: one may be the sender)
        self.table.setRowCount(len(shown))
        for r, g in enumerate(shown):
            self.table.setItem(r, COL_SCRIPT, _item(LABELS[g]))
            if g not in covered:
                self.table.setItem(r, COL_DRAWN_BY, _item(NOBODY, self._theme.muted))
                self.table.setItem(r, COL_COUNTS, _item(NO_COUNT, self._theme.muted))
                continue
            auto_key = smart.smart_supplier(g, counts, keys)
            combo = QComboBox()
            combo.addItem(AUTO_PREFIX + display.get(auto_key, "?"))
            for key in keys:
                combo.addItem(display[key])
            pinned = pins.get(g)
            combo.setCurrentIndex(keys.index(pinned) + 1 if pinned in keys else 0)
            combo.setToolTip("Which font draws this script. Auto picks the highest font in your list that "
                             "draws it well.")
            combo.setEnabled(not self._locked)
            combo.currentIndexChanged.connect(lambda index, g=g: self._on_supplier_chosen(g, index))
            self.table.setCellWidget(r, COL_DRAWN_BY, combo)
            ranked = sorted((k for k in keys if counts[k][g]), key=lambda k: (-counts[k][g], keys.index(k)))
            supplier = rules.get(g)
            if supplier is not None and 0 <= supplier < len(keys) and keys[supplier] in ranked:
                ranked.remove(keys[supplier])
                ranked.insert(0, keys[supplier])
            self.table.setItem(r, COL_COUNTS, _item(" · ".join(f"{names[k]} {counts[k][g]:,}" for k in ranked)))

    def _refresh_report(self) -> None:
        """The last build's report (its warnings included), else the error of a failed build, else a note."""
        report = getattr(self.controller, "report", None)
        detail = getattr(self.controller, "error_detail", None)
        if report is not None:
            text = report.as_text()
        elif detail:
            text = detail
        else:
            text = NO_BUILD_TEXT
        if text != self.report_text.toPlainText():
            self.report_text.setPlainText(text)

    # ----- widgets -> model -----
    def _on_supplier_chosen(self, group_id: str, index: int) -> None:
        keys = self.model.keys()
        self.model.set_pin(group_id, keys[index - 1] if 0 < index <= len(keys) else None)

    def _on_base_chosen(self, index: int) -> None:
        keys = self.model.keys()
        self.model.set_base(keys[index - 1] if 0 < index <= len(keys) else None)

    def _on_defaults_edited(self, *_args) -> None:
        weight = self.default_weight_combo.currentData()
        self.model.set_defaults(weight, self.default_scale_spin.value() / 100)

    def _on_show_all_toggled(self, checked: bool) -> None:
        self.show_all_button.setText(SHOW_COVERED_TEXT if checked else SHOW_ALL_TEXT)
        self._rebuild_table()

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label
