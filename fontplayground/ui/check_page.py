"""Step 2, Check: what each font supplies, how the mix will look, and who supplies what.

Left: one card per material in priority order (rank badge, name, a one-line sample drawn in that very font,
its share of the plan, ▲▼, a collapsed Adjust area whose title names any boldness or size set) and a collapsed
Advanced area. Right: the composite preview, the characters no font covers, the model's glyph-budget warning
(an amber callout) and the "Who supplies what" table. Everything shown comes from the ForgeModel; every action
goes back through it. The page never owns the primary button (the tray does). While a forge runs the app locks
the page (set_locked): every control that could change the spec is disabled, the previews stay live.
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QToolButton, QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace
from fontplayground.engine.scripts import GROUP_IDS, GROUPS, LABELS, group_of
from fontplayground.engine.spec import Plan
from fontplayground.ui import smart
from fontplayground.ui.model import ForgeModel, MaterialRow
from fontplayground.ui.preview import PreviewWidget, default_wght, make_font
from fontplayground.ui.theme import LIGHT, Theme

FaceKey = tuple[str, int]

SAMPLE_LINE = "Aa Ëé Ωж 漢あ한 ①"
SAMPLE_PT = 16
AS_IS = "As is"
WEIGHT_CHOICES = [AS_IS] + [str(w) for w in range(100, 950, 50)]
SCALE_RANGE = (10, 1000)              # percent
MAX_PLAN_GROUPS = 3                   # groups named on a card's plan line before "…"
MAX_MISSING_CHARS = 20                # uncovered sample characters listed before "…" (the tooltip has them all)
MAIN_CHOICE = "Main"                  # first entry of the "Line spacing from" combo
PLACEHOLDER_TEXT = "No fonts yet — go back to Pick fonts."
PENDING_TEXT = "Working out what it supplies…"
ADDS_NOTHING_TEXT = "adds nothing — everything it has is already covered above"
LINE_SPACING_BADGE = "line spacing"
ADJUST_TEXT = "Adjust"
MISSING_PREFIX = "Not covered by any font: "
NOBODY, NO_COUNT = "nobody", "—"
TABLE_COLUMNS = ["Script", "Supplied by", "Characters"]
COL_SCRIPT, COL_SUPPLIER, COL_COUNTS = range(3)
SHOW_ALL_TEXT = f"Show all {len(GROUPS)} scripts"
SHOW_COVERED_TEXT = "Show only covered scripts"

STYLE = """
QFrame#card { background: $surface; border: 1px solid $border_soft; border-radius: 8px; }
QFrame#placeholder { background: $surface; border: 1px dashed $border; border-radius: 8px; }
QLabel#placeholderText { color: $muted; }
QLabel#rank { background: $surface_alt; color: $text_secondary; border-radius: 6px; padding: 1px 7px; font-weight: 600; }
QLabel#rank[main="true"] { background: $accent; color: $on_accent; }
QLabel#baseBadge { background: $ok_soft; color: $ok; border: 1px solid $ok_soft_border; border-radius: 6px;
                   padding: 0 6px; font-size: 11px; }
QLabel#nothingBadge { background: $danger_soft; color: $danger; border: 1px solid $danger_soft_border;
                      border-radius: 6px; padding: 1px 6px; font-size: 11px; }
QLabel#plan { color: $muted; }
QLabel#sectionTitle { font-weight: 600; font-size: 14px; color: $text; }
QLabel#missing { color: $danger; }
QLabel#glyphWarning { background: $warn_soft; border: 1px solid $warn_border; border-radius: 6px; padding: 6px 10px;
                      color: $warn_text; }
QLabel#fieldLabel { color: $text_secondary; }
QTextEdit#sample { background: transparent; border: none; }
QToolButton#move { border: 1px solid $border; border-radius: 6px; background: $surface; padding: 0 5px;
                   color: $text_secondary; }
QToolButton#move:hover { border-color: $accent; color: $accent; }
QToolButton#move:disabled { color: $faint; border-color: $border_soft; }
QToolButton#disclosure { border: none; background: transparent; color: $accent; padding: 2px 0; }
QToolButton#disclosure:hover { color: $accent_hover; }
QTableWidget#suppliers { background: $surface; border: 1px solid $border_soft; border-radius: 6px;
                         gridline-color: $border_soft; }
QPushButton#showAll { border: 1px solid $border; border-radius: 6px; background: transparent; padding: 4px 10px;
                      color: $text_secondary; }
QPushButton#showAll:hover { border-color: $accent; color: $accent; }
QPushButton#showAll:checked { border-color: $accent; color: $accent; }
"""


# ----- small helpers (pure) -----------------------------------------------------------------------
def rank_text(rank: int) -> str:
    return "Main" if rank == 0 else str(rank + 1)


def weight_choice(weight: int | None) -> str:
    """Model weight -> combo text ('As is' for None)."""
    return AS_IS if weight is None else str(weight)


def choice_weight(text: str) -> int | None:
    """Combo text -> model weight (None for 'As is')."""
    return None if text == AS_IS else int(text)


def scale_percent(scale: float | None) -> int:
    return 100 if scale is None else round(scale * 100)


def percent_scale(percent: int) -> float | None:
    """Spin value -> model scale; 100 % means 'no adjustment' (None)."""
    return None if percent == 100 else percent / 100


def group_tally(codepoints: Iterable[int]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for cp in codepoints:
        g = group_of(cp)
        tally[g] = tally.get(g, 0) + 1
    return tally


def plan_line(codepoints: Iterable[int]) -> str:
    """'supplies Han 20,902 · Kana 300 · … (29,221 characters)': a material's biggest groups in its share."""
    tally = group_tally(codepoints)
    total = sum(tally.values())
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], GROUP_IDS.index(kv[0])))
    parts = [f"{LABELS[g]} {n:,}" for g, n in ranked[:MAX_PLAN_GROUPS]]
    if len(ranked) > MAX_PLAN_GROUPS:
        parts.append("…")
    return f"supplies {' · '.join(parts)} ({total:,} {'character' if total == 1 else 'characters'})"


def short_names(faces: Iterable[FontFace]) -> dict[FaceKey, str]:
    """The family name when it identifies the material on its own, else 'Family Style'."""
    faces = list(faces)
    families = [f.family for f in faces]
    return {f.key: (f.family if families.count(f.family) == 1 else f.display_name) for f in faces}


def adjust_title(weight: int | None, scale: float | None) -> str:
    """'Adjust', 'Adjust · boldness 700', 'Adjust · size 110 %' or 'Adjust · boldness 700 · size 110 %'."""
    parts = [ADJUST_TEXT]
    if weight is not None:
        parts.append(f"boldness {weight}")
    if scale is not None and scale_percent(scale) != 100:
        parts.append(f"size {scale_percent(scale)} %")
    return " · ".join(parts)


def sample_wght(face: FontFace, weight: int | None) -> float | None:
    """The 'wght' axis value to draw a card's sample line at: the boldness chosen for the material, kept within
    the axis range, else the axis default; None for a font without a weight axis (synthetic bold is not shown)."""
    axis = next((a for a in face.axes if a[0] == "wght"), None)
    if axis is None:
        return None
    if weight is None:
        return default_wght(face.axes)
    _tag, lo, _default, hi = axis
    return float(min(max(weight, lo), hi))


def render_sample(edit: QTextEdit, face: FontFace, text: str = SAMPLE_LINE, size: int = SAMPLE_PT,
                  wght: float | None = None, missing_color: str = LIGHT.missing) -> None:
    """Fill `edit` with `text` in the face's own font; characters the face lacks get `missing_color` behind them.

    `wght` (variable fonts): the weight-axis value to draw at, the axis default when None.
    """
    font = make_font(face.path, face.style, face.family, size, default_wght(face.axes) if wght is None else wght)
    edit.clear()
    doc = edit.document()
    doc.setDocumentMargin(2)
    doc.setDefaultFont(font)
    plain = QTextCharFormat()
    plain.setFont(font)
    missing = QTextCharFormat()
    missing.setFont(font)
    missing.setBackground(QBrush(QColor(missing_color)))
    cursor = QTextCursor(doc)
    for ch in text:
        lacking = not ch.isspace() and ord(ch) not in face.codepoints
        cursor.insertText(ch, missing if lacking else plain)
    edit.setFixedHeight(int(doc.size().height()) + 4)


def _restyle(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _muted_item(text: str, color: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setForeground(QBrush(QColor(color)))
    return item


def _plain_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setToolTip(text)
    return item


# ----- widgets -----------------------------------------------------------------------------------
class Disclosure(QToolButton):
    """A '▸ Adjust' / '▾ Adjust' button that shows or hides one body widget (hidden to start with)."""

    def __init__(self, text: str, body: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.body = body
        self.setObjectName("disclosure")
        self.setText(text)
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setArrowType(Qt.ArrowType.RightArrow)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.toggled.connect(self._on_toggled)
        body.setVisible(False)

    def _on_toggled(self, open_: bool) -> None:
        self.body.setVisible(open_)
        self.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)


class MaterialCard(QFrame):
    """One material: rank, name, sample line in its own font, plan share, ▲▼ and the Adjust area."""
    moveRequested = Signal(object, int)             # key, delta (-1 = up, +1 = down)
    adjustChanged = Signal(object, object, object)  # key, weight | None, scale | None

    def __init__(self, row: MaterialRow, rank: int, count: int, is_base: bool,
                 parent: QWidget | None = None, default_weight: int | None = None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.key: FaceKey = row.face.key
        self.face: FontFace = row.face
        self._locked = False
        self._theme = theme
        self._can_move = (False, False)                  # (up, down) by rank; the lock overrides both
        effective = row.weight if row.weight is not None else default_weight
        self._shown_wght: float | None = sample_wght(row.face, effective)   # what the sample line is drawn at
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.rank_badge = QLabel()
        self.rank_badge.setObjectName("rank")
        self.name_label = QLabel()
        self.name_label.setObjectName("name")
        font = self.name_label.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 1)
        self.name_label.setFont(font)
        self.base_badge = QLabel(LINE_SPACING_BADGE)
        self.base_badge.setObjectName("baseBadge")
        self.base_badge.setToolTip("The result takes its line spacing from this font.")
        self.up_button = QToolButton()
        self.up_button.setObjectName("move")
        self.up_button.setText("▲")
        self.up_button.setToolTip("Move up: it gets to supply characters before the fonts below it")
        self.down_button = QToolButton()
        self.down_button.setObjectName("move")
        self.down_button.setText("▼")
        self.down_button.setToolTip("Move down: the fonts above it get first pick")
        for button in (self.up_button, self.down_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head.addWidget(self.rank_badge)
        head.addWidget(self.name_label)
        head.addWidget(self.base_badge)
        head.addStretch(1)
        head.addWidget(self.up_button)
        head.addWidget(self.down_button)
        layout.addLayout(head)

        self.sample = QTextEdit()
        self.sample.setObjectName("sample")
        self.sample.setReadOnly(True)
        self.sample.setFrameShape(QFrame.Shape.NoFrame)
        self.sample.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.sample.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sample.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sample.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sample.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.sample.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sample.setToolTip("Drawn in this font. Red: a character this font cannot draw.")
        render_sample(self.sample, row.face, wght=self._shown_wght, missing_color=self._theme.missing)
        layout.addWidget(self.sample)

        self.plan_label = QLabel(PENDING_TEXT)
        self.plan_label.setObjectName("plan")
        self.plan_label.setWordWrap(True)
        self.nothing_badge = QLabel(ADDS_NOTHING_TEXT)
        self.nothing_badge.setObjectName("nothingBadge")
        self.nothing_badge.setWordWrap(True)
        self.nothing_badge.hide()
        layout.addWidget(self.plan_label)
        layout.addWidget(self.nothing_badge)

        self.adjust_area = QWidget()
        adjust = QHBoxLayout(self.adjust_area)
        adjust.setContentsMargins(0, 0, 0, 0)
        adjust.setSpacing(8)
        weight_label = QLabel("Boldness")
        weight_label.setObjectName("fieldLabel")
        self.weight_combo = QComboBox()
        self.weight_combo.addItems(WEIGHT_CHOICES)
        self.weight_combo.setToolTip("Make this font bolder or lighter in the result ('As is' keeps it unchanged)")
        scale_label = QLabel("Size")
        scale_label.setObjectName("fieldLabel")
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(*SCALE_RANGE)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(100)
        self.scale_spin.setKeyboardTracking(False)
        self.scale_spin.setToolTip("Scale this font's characters in the result (100 % keeps them as they are)")
        adjust.addWidget(weight_label)
        adjust.addWidget(self.weight_combo)
        adjust.addSpacing(8)
        adjust.addWidget(scale_label)
        adjust.addWidget(self.scale_spin)
        adjust.addStretch(1)
        self.adjust_button = Disclosure(ADJUST_TEXT, self.adjust_area)
        self.adjust_button.setToolTip("Boldness and size of this font in the result")
        layout.addWidget(self.adjust_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.adjust_area)

        self.update_from(row, rank, count, is_base, default_weight)
        self.up_button.clicked.connect(lambda: self.moveRequested.emit(self.key, -1))
        self.down_button.clicked.connect(lambda: self.moveRequested.emit(self.key, 1))
        self.weight_combo.currentIndexChanged.connect(self._emit_adjust)
        self.scale_spin.valueChanged.connect(self._emit_adjust)

    # ----- model -> card -----
    def update_from(self, row: MaterialRow, rank: int, count: int, is_base: bool,
                    default_weight: int | None = None) -> None:
        """Refresh rank, name, base badge, ▲▼, the Adjust controls and title in place (signals stay quiet).

        `default_weight` is the model's default boldness: a variable font's sample line is drawn at the
        boldness that will apply to it (its own, else the default), so the line follows the Adjust combo.
        """
        effective = row.weight if row.weight is not None else default_weight
        wght = sample_wght(row.face, effective)
        if row.face is not self.face or wght != self._shown_wght:
            self.face = row.face
            self._shown_wght = wght
            render_sample(self.sample, row.face, wght=wght, missing_color=self._theme.missing)
        self.name_label.setText(row.face.display_name)
        self.name_label.setToolTip(f"{row.face.display_name}\n{row.face.path} (face {row.face.index})")
        self.rank_badge.setText(rank_text(rank))
        self.rank_badge.setToolTip("Main: the font whose letters lead" if rank == 0 else f"Priority {rank + 1}")
        if self.rank_badge.property("main") != (rank == 0):
            self.rank_badge.setProperty("main", rank == 0)
            _restyle(self.rank_badge)
        self.base_badge.setVisible(is_base)
        self._can_move = (rank > 0, rank < count - 1)
        self._apply_enabled()
        self.weight_combo.blockSignals(True)
        self.scale_spin.blockSignals(True)
        try:
            text = weight_choice(row.weight)
            i = self.weight_combo.findText(text)
            if i < 0:  # a value outside the usual steps (from a settings file): show it anyway
                self.weight_combo.addItem(text)
                i = self.weight_combo.count() - 1
            self.weight_combo.setCurrentIndex(i)
            self.scale_spin.setValue(scale_percent(row.scale))
        finally:
            self.weight_combo.blockSignals(False)
            self.scale_spin.blockSignals(False)
        self._refresh_adjust_title()

    def set_locked(self, locked: bool) -> None:
        """A forge is running: ▲▼ and the Adjust fields are off (the sample line and plan line stay live)."""
        self._locked = bool(locked)
        self._apply_enabled()

    def is_locked(self) -> bool:
        return self._locked

    def shown_wght(self) -> float | None:
        """The weight-axis value the sample line is drawn at (None for a font without a weight axis)."""
        return self._shown_wght

    def _apply_enabled(self) -> None:
        up, down = self._can_move
        self.up_button.setEnabled(up and not self._locked)
        self.down_button.setEnabled(down and not self._locked)
        self.weight_combo.setEnabled(not self._locked)
        self.scale_spin.setEnabled(not self._locked)

    def _refresh_adjust_title(self) -> None:
        self.adjust_button.setText(adjust_title(self.weight(), self.scale()))

    def set_share(self, codepoints: set[int] | None) -> None:
        """The plan line: None while the plan is pending, the badge when the share is empty, else the summary."""
        if codepoints is None:
            self.plan_label.setText(PENDING_TEXT)
            self.plan_label.setToolTip("")
            self.plan_label.show()
            self.nothing_badge.hide()
        elif not codepoints:
            self.plan_label.hide()
            self.nothing_badge.show()
        else:
            self.plan_label.setText(plan_line(codepoints))
            self.plan_label.setToolTip(" · ".join(f"{LABELS[g]} {n:,}" for g, n in
                                                  sorted(group_tally(codepoints).items(), key=lambda kv: -kv[1])))
            self.plan_label.show()
            self.nothing_badge.hide()

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        render_sample(self.sample, self.face, wght=self._shown_wght, missing_color=theme.missing)

    # ----- card -> model -----
    def weight(self) -> int | None:
        return choice_weight(self.weight_combo.currentText())

    def scale(self) -> float | None:
        return percent_scale(self.scale_spin.value())

    def _emit_adjust(self, *_args) -> None:
        self._refresh_adjust_title()   # materialsChanged refreshes it too; this keeps it right if the model declines
        self.adjustChanged.emit(self.key, self.weight(), self.scale())


class CheckPage(QWidget):
    """Step 2: material cards and Advanced on the left; composite preview, missing characters and the table right."""

    def __init__(self, model: ForgeModel, preview: PreviewWidget, parent: QWidget | None = None,
                 theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.model = model
        self.preview = preview
        self.cards: list[MaterialCard] = []
        self._table_groups: list[str] = []
        self._locked = False
        self.setObjectName("checkPage")
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))   # cards and the table come below, built in this theme by refresh()

        # ----- left pane: cards + Advanced, in a scroll area -----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self.cards_layout = QVBoxLayout(host)
        self.cards_layout.setContentsMargins(0, 0, 6, 0)
        self.cards_layout.setSpacing(8)

        self.placeholder = QFrame()
        self.placeholder.setObjectName("placeholder")
        self.placeholder.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setContentsMargins(12, 14, 12, 14)
        self.placeholder_label = QLabel(PLACEHOLDER_TEXT)
        self.placeholder_label.setObjectName("placeholderText")
        self.placeholder_label.setWordWrap(True)
        placeholder_layout.addWidget(self.placeholder_label)
        self.cards_layout.addWidget(self.placeholder)

        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        form.setContentsMargins(12, 4, 12, 4)
        self.base_combo = QComboBox()
        self.base_combo.setToolTip("Which font's line spacing the result uses (Main unless you choose another)")
        self.default_weight_combo = QComboBox()
        self.default_weight_combo.addItems(WEIGHT_CHOICES)
        self.default_weight_combo.setToolTip("Boldness for every font that has no adjustment of its own")
        self.default_scale_spin = QSpinBox()
        self.default_scale_spin.setRange(*SCALE_RANGE)
        self.default_scale_spin.setSuffix(" %")
        self.default_scale_spin.setValue(100)
        self.default_scale_spin.setKeyboardTracking(False)
        self.default_scale_spin.setToolTip("Size for every font that has no adjustment of its own")
        form.addRow("Line spacing from", self.base_combo)
        form.addRow("Default boldness", self.default_weight_combo)
        form.addRow("Default size", self.default_scale_spin)
        self.advanced_button = Disclosure("Advanced", self.advanced)
        self.advanced_button.setToolTip("Line spacing, default boldness and default size")
        self.cards_layout.addWidget(self.advanced_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.cards_layout.addWidget(self.advanced)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(host)
        left_layout.addWidget(self.scroll)

        # ----- right pane: composite preview, missing characters, the table -----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.preview_title = QLabel("How the result will look")
        self.preview_title.setObjectName("sectionTitle")
        right_layout.addWidget(self.preview_title)
        right_layout.addWidget(self.preview, 3)
        self.missing_label = QLabel("")
        self.missing_label.setObjectName("missing")
        self.missing_label.setWordWrap(True)
        self.missing_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.missing_label.hide()
        right_layout.addWidget(self.missing_label)
        self.table_title = QLabel("Who supplies what")
        self.table_title.setObjectName("sectionTitle")
        right_layout.addWidget(self.table_title)
        self.glyph_warning_label = QLabel("")     # amber callout: the model's word on the glyph budget
        self.glyph_warning_label.setObjectName("glyphWarning")
        self.glyph_warning_label.setWordWrap(True)
        self.glyph_warning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.glyph_warning_label.hide()
        right_layout.addWidget(self.glyph_warning_label)
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
        header.setSectionResizeMode(COL_SUPPLIER, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_COUNTS, QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(self.table, 2)
        self.show_all_button = QPushButton(SHOW_ALL_TEXT)
        self.show_all_button.setObjectName("showAll")
        self.show_all_button.setCheckable(True)
        self.show_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.show_all_button.setToolTip("Also list the scripts none of your fonts covers")
        right_layout.addWidget(self.show_all_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        left.setMinimumWidth(420)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.splitter)

        # ----- wiring (bound methods: Qt drops them cleanly if the page dies before the model) -----
        self.preview.sampleChanged.connect(self.model.set_sample_text)
        self.model.sampleChanged.connect(self.preview.set_sample_text)
        self.preview.sampleChanged.connect(self._on_sample_edited)
        self.model.sampleChanged.connect(self._on_sample_edited)   # after set_sample_text: the preview is current
        self.model.materialsChanged.connect(self._on_materials_changed)
        self.model.planChanged.connect(self._on_plan_changed)
        self.base_combo.currentIndexChanged.connect(self._on_base_chosen)
        self.default_weight_combo.currentIndexChanged.connect(self._on_defaults_edited)
        self.default_scale_spin.valueChanged.connect(self._on_defaults_edited)
        self.show_all_button.toggled.connect(self._on_show_all_toggled)
        self.preview.set_sample_text(self.model.sample_text)
        self.refresh()

    # ----- public API -----
    def refresh(self) -> None:
        """Rebuild everything from the model: cards, Advanced, the table, and the preview from the current plan."""
        self._on_materials_changed()
        self._on_plan_changed(self.model.plan)

    def apply_theme(self, theme: Theme) -> None:
        """Re-render the sheet, every card's sample line and the table in `theme`."""
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        for card in self.cards:
            card.apply_theme(theme)
        self._rebuild_table()

    def table_groups(self) -> list[str]:
        """Group ids listed in the table, top to bottom."""
        return list(self._table_groups)

    def table_row(self, group_id: str) -> int | None:
        return self._table_groups.index(group_id) if group_id in self._table_groups else None

    def supplier_combo(self, group_id: str) -> QComboBox | None:
        """The 'Supplied by' combo of a covered group (None for a group nobody covers or one not listed)."""
        row = self.table_row(group_id)
        widget = self.table.cellWidget(row, COL_SUPPLIER) if row is not None else None
        return widget if isinstance(widget, QComboBox) else None

    def cell_text(self, group_id: str, column: int) -> str:
        row = self.table_row(group_id)
        item = self.table.item(row, column) if row is not None else None
        return item.text() if item is not None else ""

    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        """While a forge runs nothing here may change the spec: every card control (▲▼, Adjust), the
        'Supplied by' combos and the Advanced fields are disabled. The previews and the table stay live."""
        locked = bool(locked)
        if locked == self._locked:
            return
        self._locked = locked
        for card in self.cards:
            card.set_locked(locked)
        self._apply_advanced_enabled()
        for g in self._table_groups:
            combo = self.supplier_combo(g)
            if combo is not None:
                combo.setEnabled(not locked)

    # ----- model -> widgets -----
    def _on_materials_changed(self) -> None:
        rows = self.model.rows
        if [c.key for c in self.cards] != [r.face.key for r in rows]:
            self._rebuild_cards(rows)
        else:
            self._update_cards(rows)
        self.placeholder.setVisible(not rows)
        self._refresh_advanced()
        self._rebuild_table()
        self._refresh_glyph_warning()

    def _on_plan_changed(self, plan: Plan | None) -> None:
        rows = self.model.rows
        keys = [r.face.key for r in rows]
        fonts = {r.face.key: (r.face.path, r.face.style, r.face.family, r.face.axes) for r in rows}
        if plan is None or not fonts:
            self.preview.set_plan({}, lambda cp: None)
            for card in self.cards:
                card.set_share(None)
        else:
            source = plan.source

            def source_of(cp: int) -> FaceKey | None:
                i = source.get(cp)
                return keys[i] if i is not None and 0 <= i < len(keys) else None

            self.preview.set_plan(fonts, source_of)
            for i, card in enumerate(self.cards):
                card.set_share(plan.assignments.get(i, set()))
        self._refresh_missing()
        self._refresh_glyph_warning()

    def _on_sample_edited(self, _text: str) -> None:
        self._refresh_missing()

    def _rebuild_cards(self, rows: list[MaterialRow]) -> None:
        for card in self.cards:
            self.cards_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.cards = []
        base = self.model.base_index()
        default_weight = self.model.default_weight
        first = self.cards_layout.indexOf(self.placeholder) + 1
        for i, row in enumerate(rows):
            card = MaterialCard(row, i, len(rows), i == base, default_weight=default_weight, theme=self._theme)
            card.set_locked(self._locked)
            card.moveRequested.connect(self._on_move_requested)
            card.adjustChanged.connect(self._on_adjust_changed)
            self.cards_layout.insertWidget(first + i, card)
            self.cards.append(card)

    def _update_cards(self, rows: list[MaterialRow]) -> None:
        base = self.model.base_index()
        default_weight = self.model.default_weight
        for i, (card, row) in enumerate(zip(self.cards, rows)):
            card.update_from(row, i, len(rows), i == base, default_weight)

    def _refresh_advanced(self) -> None:
        rows = self.model.rows
        base_key = self.model.base_key
        base_index = self.model.index_of(base_key) if base_key is not None else None
        for w in (self.base_combo, self.default_weight_combo, self.default_scale_spin):
            w.blockSignals(True)
        try:
            self.base_combo.clear()
            self.base_combo.addItem(MAIN_CHOICE)
            for row in rows:
                self.base_combo.addItem(row.face.display_name)
            self.base_combo.setCurrentIndex(base_index + 1 if base_index is not None else 0)
            text = weight_choice(self.model.default_weight)
            i = self.default_weight_combo.findText(text)
            if i < 0:
                self.default_weight_combo.addItem(text)
                i = self.default_weight_combo.count() - 1
            self.default_weight_combo.setCurrentIndex(i)
            self.default_scale_spin.setValue(scale_percent(self.model.default_scale))
        finally:
            for w in (self.base_combo, self.default_weight_combo, self.default_scale_spin):
                w.blockSignals(False)
        self._apply_advanced_enabled()

    def _apply_advanced_enabled(self) -> None:
        self.base_combo.setEnabled(bool(self.model.rows) and not self._locked)
        self.default_weight_combo.setEnabled(not self._locked)
        self.default_scale_spin.setEnabled(not self._locked)

    def _refresh_glyph_warning(self) -> None:
        """The model's warning about the glyph budget (an API the model may not have yet), as an amber callout."""
        text = str(getattr(self.model, "glyph_warning", lambda: "")() or "")
        self.glyph_warning_label.setText(text)
        self.glyph_warning_label.setVisible(bool(text))

    def _rebuild_table(self) -> None:
        rows = self.model.rows
        faces = [r.face for r in rows]
        keys = [f.key for f in faces]
        counts = smart.group_counts(faces)
        covered = [g for g in GROUP_IDS if any(counts[k][g] for k in keys)]
        self.show_all_button.setVisible(len(covered) < len(GROUP_IDS))   # nothing to reveal when all are covered
        shown = list(GROUP_IDS) if self.show_all_button.isChecked() else covered
        rules = self.model.script_rules() if rows else {}
        pins = self.model.pins
        names = short_names(faces)
        display = {f.key: f.display_name for f in faces}
        self._table_groups = shown
        self.table.setRowCount(0)
        self.table.setRowCount(len(shown))
        for r, g in enumerate(shown):
            self.table.setItem(r, COL_SCRIPT, _plain_item(LABELS[g]))
            if g not in covered:
                self.table.setItem(r, COL_SUPPLIER, _muted_item(NOBODY, self._theme.muted))
                self.table.setItem(r, COL_COUNTS, _muted_item(NO_COUNT, self._theme.muted))
                continue
            auto_key = smart.smart_supplier(g, counts, keys)
            combo = QComboBox()
            combo.addItem(f"Auto → {display.get(auto_key, '?')}")
            for key in keys:
                combo.addItem(display[key])
            pinned = pins.get(g)
            combo.setCurrentIndex(keys.index(pinned) + 1 if pinned in keys else 0)
            combo.setToolTip("Which font draws this script. Auto picks the highest font in your list that covers it well.")
            combo.setEnabled(not self._locked)
            combo.currentIndexChanged.connect(lambda index, g=g: self._on_supplier_chosen(g, index))
            self.table.setCellWidget(r, COL_SUPPLIER, combo)
            ranked = sorted((k for k in keys if counts[k][g]), key=lambda k: (-counts[k][g], keys.index(k)))
            supplier = rules.get(g)
            if supplier is not None and 0 <= supplier < len(keys) and keys[supplier] in ranked:
                ranked.remove(keys[supplier])
                ranked.insert(0, keys[supplier])
            self.table.setItem(r, COL_COUNTS, _plain_item(" · ".join(f"{names[k]} {counts[k][g]:,}" for k in ranked)))

    def _refresh_missing(self) -> None:
        missing = self.preview.missing_characters() if self.preview.in_plan_mode() else []
        if missing:
            shown = " ".join(missing[:MAX_MISSING_CHARS]) + (" …" if len(missing) > MAX_MISSING_CHARS else "")
            self.missing_label.setText(MISSING_PREFIX + shown)
            self.missing_label.setToolTip(" ".join(missing))
            self.missing_label.show()
        else:
            self.missing_label.setText("")
            self.missing_label.setToolTip("")
            self.missing_label.hide()

    # ----- widgets -> model -----
    def _on_move_requested(self, key: FaceKey, delta: int) -> None:
        i = self.model.index_of(key)
        if i is not None:
            self.model.move(key, i + delta)

    def _on_adjust_changed(self, key: FaceKey, weight: int | None, scale: float | None) -> None:
        self.model.set_adjust(key, weight, scale)

    def _on_base_chosen(self, index: int) -> None:
        keys = self.model.keys()
        self.model.set_base(keys[index - 1] if 0 < index <= len(keys) else None)

    def _on_defaults_edited(self, *_args) -> None:
        self.model.set_defaults(choice_weight(self.default_weight_combo.currentText()),
                                self.default_scale_spin.value() / 100)

    def _on_supplier_chosen(self, group_id: str, index: int) -> None:
        keys = self.model.keys()
        self.model.set_pin(group_id, keys[index - 1] if 0 < index <= len(keys) else None)

    def _on_show_all_toggled(self, checked: bool) -> None:
        self.show_all_button.setText(SHOW_COVERED_TEXT if checked else SHOW_ALL_TEXT)
        self._rebuild_table()
