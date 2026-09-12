"""MaterialsTray: the always-visible strip at the bottom of the window.

Chips in priority order (drag to reorder, × to remove, "+ add"), a recap, a hint about what the sample
still needs (with "Add <family>" suggestions), and the Back / primary buttons. Everything the tray shows
comes from the ForgeModel; every action goes back through it.

The tray never dictates the window width: the recap and the hint take whatever room is left and elide
(full text in their tooltips), suggestion buttons disappear as the tray narrows, and the primary button's
label is capped (its tooltip carries the full text).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
                               QMenu, QPushButton, QSizePolicy, QStyle, QStyleOption, QToolButton, QVBoxLayout, QWidget)

from fontplayground.engine.scripts import LABELS
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.theme import LIGHT, Theme, retint, tint

FaceKey = tuple[str, int]

MAX_SUGGESTIONS = 3
MAX_HINT_CHARS = 20            # missing characters shown in the hint before "…" (the tooltip has them all)
MAX_PRIMARY_CHARS = 42         # longer primary labels lose their middle; the tooltip keeps the whole text
PRIMARY_MIN_WIDTH = 260        # the primary button never asks the window for more than this (its text may clip)
SUGGESTION_MIN_WIDTHS = (0, 860, 1000)   # tray width needed to show the 1st, 2nd and 3rd suggestion button
MIN_HEIGHT, MAX_HEIGHT = 64, 84

STYLE = """
QWidget#tray { background: $surface; border-top: 1px solid $border; }
QListWidget#chips { background: transparent; border: none; }
QListWidget#chips::item { border: none; padding: 0; margin: 0; }
QListWidget#chips::item:selected, QListWidget#chips::item:hover { background: transparent; }
QFrame#chip { background: $surface_alt; border: 1px solid $border; border-radius: 13px; }
QFrame#chip[main="true"] { background: $accent_soft; border: 1px solid $accent_soft_border; }
QLabel#chipText { background: transparent; border: none; color: $text; }
QFrame#chip[main="true"] QLabel#chipText { color: $accent_soft_text; font-weight: 600; }
QToolButton#chipClose { border: none; background: transparent; color: $muted; font-weight: bold; padding: 0 2px; }
QToolButton#chipClose:hover { color: $danger; }
QPushButton#addButton { border: 1px dashed $faint; border-radius: 13px; background: transparent;
                        color: $text_secondary; padding: 3px 12px; }
QPushButton#addButton:hover { border-color: $accent; color: $accent; }
QPushButton#addButton:disabled { color: $faint; border-color: $border_soft; }
QPushButton#suggest { border: 1px solid $danger_soft_border; border-radius: 10px; background: $danger_soft;
                      color: $danger; padding: 1px 8px; }
QPushButton#suggest:hover { background: $danger_soft_hover; }
QLabel#recap { color: $text_secondary; }
QPushButton#backButton { border: 1px solid $border; border-radius: 6px; background: transparent; padding: 6px 12px;
                         color: $text; }
QPushButton#backButton:hover { background: $surface_alt; }
QPushButton#backButton:disabled { color: $faint; border-color: $border_soft; background: transparent; }
QPushButton#primaryButton { background: $accent; color: $on_accent; border: none; border-radius: 6px;
                            padding: 6px 16px; font-weight: 600; }
QPushButton#primaryButton[attached="true"] { border-top-right-radius: 0; border-bottom-right-radius: 0; }
QPushButton#primaryButton:hover { background: $accent_hover; }
QPushButton#primaryButton:disabled { background: $accent_disabled; color: $accent_disabled_text; }
QToolButton#primaryMenu { background: $accent; color: $on_accent; border: none; border-left: 1px solid $accent_hover;
                          border-top-right-radius: 6px; border-bottom-right-radius: 6px; padding: 0 5px;
                          font-weight: 600; }
QToolButton#primaryMenu:hover { background: $accent_hover; }
QToolButton#primaryMenu:disabled { background: $accent_disabled; color: $accent_disabled_text; }
QToolButton#primaryMenu::menu-indicator { image: none; }
"""


def chip_label(rank: int, display_name: str) -> str:
    return f"{'Main' if rank == 0 else rank + 1} · {display_name}"


def elide_middle(text: str, limit: int = MAX_PRIMARY_CHARS) -> str:
    """`text` when it has at most `limit` characters, else its head and tail around '…' (`limit` characters in all)."""
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return text[:head] + "…" + text[len(text) - tail:]


class ElidedLabel(QLabel):
    """A one-line label that never asks the layout for room.

    It takes what the layout leaves (QSizePolicy.Ignored horizontally) but never more than its text needs.
    text() stays the logical text (size hints and accessibility use it); what is painted is that text cut
    to the current width with '…', re-measured on every resize. The tooltip tells the whole story whenever
    the painted text does not: when it is elided, or when the caller already shortened it (full_text).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_text(self, text: str, full_text: str | None = None) -> None:
        self._full = text if full_text is None else full_text
        self.setText(text)
        self.setMaximumWidth(self.sizeHint().width())   # leftover space stays free instead of padding the label
        self._update_tooltip()

    def full_text(self) -> str:
        return self._full

    def elided_text(self) -> str:
        """What is painted right now: text() cut to the current width with '…' where it does not fit."""
        return QFontMetrics(self.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight, self._text_rect().width())

    def _text_rect(self) -> QRect:
        m = self.margin()
        return self.contentsRect().adjusted(m, m, -m, -m)

    def _update_tooltip(self) -> None:
        self.setToolTip("" if self.elided_text() == self._full else self._full)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_tooltip()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        self.drawFrame(painter)   # a stylesheet border or background, when there is one
        option = QStyleOption()
        option.initFrom(self)
        flags = int(QStyle.visualAlignment(self.layoutDirection(), self.alignment())) | int(Qt.TextFlag.TextSingleLine)
        self.style().drawItemText(painter, self._text_rect(), flags, option.palette, self.isEnabled(),
                                  self.elided_text(), self.foregroundRole())


class PrimaryButton(QPushButton):
    """The primary button: shrinkable in the layout's eyes so a long label never widens the window."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), PRIMARY_MIN_WIDTH), hint.height())


class SuggestionsBox(QWidget):
    """The row of "Add <family>" buttons: served first, never clipped, never a minimum.

    Preferred horizontally with no minimum: the layout gives it the natural width of its visible buttons before
    the labels get anything (a cut-off button looks broken; an elided label does not), yet it never widens the
    window, since it shrinks to nothing when even the buttons alone do not fit. Which buttons are visible is the
    tray's decision (SUGGESTION_MIN_WIDTHS).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())


class Chip(QFrame):
    """One material: '<rank> · <name>' and a small × button."""
    removeClicked = Signal(object)  # face key

    def __init__(self, key: FaceKey, text: str, is_main: bool, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("chip")
        self.setProperty("main", is_main)
        self.setToolTip(tooltip)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 4, 3)
        layout.setSpacing(4)
        self.label = QLabel(text)
        self.label.setObjectName("chipText")
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # presses reach the list: drag
        self.close_button = QToolButton()
        self.close_button.setObjectName("chipClose")
        self.close_button.setText("×")
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip("Remove from materials")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(lambda: self.removeClicked.emit(self.key))
        layout.addWidget(self.label)
        layout.addWidget(self.close_button)

    def text(self) -> str:
        return self.label.text()


class ChipList(QListWidget):
    """Horizontal list with drag-to-reorder; reports the new key order after a drop and Delete on a chip."""
    orderChanged = Signal()           # the list's own order changed by a drop; read keys()
    removeRequested = Signal(object)  # face key of the current chip (Delete / Backspace)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chips")
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setSpacing(3)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.model().rowsMoved.connect(self._on_rows_moved)

    def _on_rows_moved(self, *_args) -> None:
        self.orderChanged.emit()

    def keys(self) -> list[FaceKey]:
        return [tuple(self.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.count())]

    def dropEvent(self, event) -> None:  # noqa: N802
        super().dropEvent(event)
        self.orderChanged.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            item = self.currentItem()
            if item is not None:
                self.removeRequested.emit(tuple(item.data(Qt.ItemDataRole.UserRole)))
                return
        super().keyPressEvent(event)


class MaterialsTray(QWidget):
    backClicked = Signal()
    primaryClicked = Signal()
    addClicked = Signal()

    def __init__(self, model: ForgeModel, parent: QWidget | None = None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.model = model
        self._theme = theme
        self._sync_pending = False
        self.setObjectName("tray")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(theme.render(STYLE))
        self.setMinimumHeight(MIN_HEIGHT)
        self.setMaximumHeight(MAX_HEIGHT)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 5, 10, 5)
        root.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(2)
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        self.list = ChipList()
        self.list.setFixedHeight(32)
        self.add_button = QPushButton("+ add")
        self.add_button.setObjectName("addButton")
        self.add_button.setToolTip("Pick another font")
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        chips_row.addWidget(self.list, 1)
        chips_row.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignVCenter)
        left.addLayout(chips_row)

        # recap, hint and suggestions share the row: none of them has a minimum, each is capped at what it
        # needs, and the leftover stays free (no trailing stretch: the labels are the ones that give way).
        # The suggestions box (stretch 0, Preferred) is served its natural width first so its buttons are
        # never cut mid-text; the two labels (Ignored, stretch 1 each) share whatever is left and elide.
        info_row = QHBoxLayout()
        info_row.setSpacing(10)
        self.recap_label = ElidedLabel()
        self.recap_label.setObjectName("recap")
        self.hint_label = ElidedLabel()
        self.hint_label.setObjectName("hint")
        self.suggestions_box = SuggestionsBox()
        self.suggestions_layout = QHBoxLayout(self.suggestions_box)
        self.suggestions_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestions_layout.setSpacing(4)
        info_row.addWidget(self.recap_label, 1)
        info_row.addWidget(self.hint_label, 1)
        info_row.addWidget(self.suggestions_box, 0)
        left.addLayout(info_row)
        root.addLayout(left, 1)

        self.back_button = QPushButton("‹ Back")
        self.back_button.setObjectName("backButton")
        primary_row = QHBoxLayout()
        primary_row.setSpacing(0)
        self.primary_button = PrimaryButton("Next ›")
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_menu_button = QToolButton()
        self.primary_menu_button.setObjectName("primaryMenu")
        self.primary_menu_button.setText("▾")
        self.primary_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.primary_menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.primary_menu_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.primary_menu_button.setToolTip("More ways to do this")
        self.primary_menu_button.hide()
        primary_row.addWidget(self.primary_button)
        primary_row.addWidget(self.primary_menu_button)
        root.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(primary_row, 0)
        root.setAlignment(primary_row, Qt.AlignmentFlag.AlignVCenter)

        self.add_button.clicked.connect(self.addClicked)
        self.back_button.clicked.connect(self.backClicked)
        self.primary_button.clicked.connect(self.primaryClicked)
        self.list.orderChanged.connect(self._schedule_order_sync)
        self.list.removeRequested.connect(self.model.remove)
        # bound methods (not lambdas): Qt drops these connections when the tray is destroyed before the model
        self.model.materialsChanged.connect(self._on_materials_changed)
        self.model.planChanged.connect(self._on_plan_changed)
        self.model.sampleChanged.connect(self._on_sample_changed)
        self._on_materials_changed()

    # ----- public API -----
    def set_primary(self, text: str, enabled: bool, tooltip: str = "") -> None:
        """Label, enabled state and tooltip of the primary button.

        A label longer than MAX_PRIMARY_CHARS loses its middle (paths keep their drive and file name); the
        full text then leads the tooltip, above `tooltip` when there is one.
        """
        shown = elide_middle(text)
        self.primary_button.setText(shown)
        self.primary_button.setEnabled(enabled)
        self.primary_button.setToolTip("\n".join(part for part in (text if shown != text else "", tooltip) if part))
        self.primary_menu_button.setFixedHeight(self.primary_button.sizeHint().height())

    def set_primary_menu(self, menu: QMenu | None) -> None:
        """Glue a '▾' menu button to the right of the primary button, or (None) remove it."""
        self.primary_menu_button.setMenu(menu)
        self.primary_menu_button.setVisible(menu is not None)
        self.primary_menu_button.setFixedHeight(self.primary_button.sizeHint().height())
        self.primary_button.setProperty("attached", menu is not None)
        self.primary_button.style().unpolish(self.primary_button)
        self.primary_button.style().polish(self.primary_button)

    def set_back_visible(self, visible: bool) -> None:
        self.back_button.setVisible(visible)

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        retint(self.hint_label, theme)

    def chip_labels(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def chip_widget(self, i: int) -> Chip:
        return self.list.itemWidget(self.list.item(i))

    def suggestion_buttons(self) -> list[QPushButton]:
        """Every suggestion button, in rank order, whether or not the tray is wide enough to show it."""
        return [self.suggestions_layout.itemAt(i).widget() for i in range(self.suggestions_layout.count())]

    # ----- model -> widgets -----
    def _on_materials_changed(self) -> None:
        self._rebuild_chips()
        self._refresh_recap()
        self._refresh_hint()
        self._settle()

    def _on_plan_changed(self, _plan) -> None:
        self._refresh_recap()
        self._settle()

    def _on_sample_changed(self, _text: str) -> None:
        self._refresh_hint()
        self._settle()

    def _settle(self) -> None:
        """Lay the tray out now, so the labels' tooltips reflect the room they get and not the room they had."""
        self.layout().activate()

    def _rebuild_chips(self) -> None:
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for i, row in enumerate(self.model.rows):
                face = row.face
                item = QListWidgetItem(chip_label(i, face.display_name))
                item.setData(Qt.ItemDataRole.UserRole, face.key)
                item.setForeground(QBrush(QColor(0, 0, 0, 0)))  # the chip widget draws the text
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
                scripts = ", ".join(LABELS.get(g, g) for g in face.scripts) or "no characters"
                chip = Chip(face.key, item.text(), i == 0, f"{face.display_name}\nCovers: {scripts}")
                chip.removeClicked.connect(self.model.remove)
                self.list.addItem(item)
                self.list.setItemWidget(item, chip)
                chip.ensurePolished()
                chip.label.ensurePolished()
                text_width = QFontMetrics(chip.label.font()).horizontalAdvance(chip.label.text())
                hint = chip.sizeHint()
                hint.setWidth(max(hint.width(), text_width + chip.close_button.sizeHint().width() + 28))
                item.setSizeHint(hint)
        finally:
            self.list.blockSignals(False)

    def _refresh_recap(self) -> None:
        n = len(self.model.rows)
        chars = len(self.model.plan.source) if self.model.plan is not None else 0
        self.recap_label.set_text(f"{n} {'font' if n == 1 else 'fonts'} · {chars:,} characters")

    def _refresh_hint(self) -> None:
        for button in self.suggestion_buttons():
            self.suggestions_layout.removeWidget(button)
            button.hide()  # gone from view at once; deletion happens on the next event-loop pass
            button.deleteLater()
        if not self.model.rows:
            self._set_hint("Pick a font to begin.", "text_secondary")
        else:
            missing = self.model.missing_sample_chars()
            if not missing:
                self._set_hint("Your sample is fully covered.", "ok")
            else:
                shown = " ".join(missing[:MAX_HINT_CHARS]) + (" …" if len(missing) > MAX_HINT_CHARS else "")
                self._set_hint(f"Your sample still needs: {shown}", "danger",
                               full=f"Your sample still needs: {' '.join(missing)}")
                for face in self.model.suggestions(MAX_SUGGESTIONS):
                    button = QPushButton(f"Add {face.family}")
                    button.setObjectName("suggest")
                    button.setToolTip(f"Add {face.display_name} to your materials")
                    button.setCursor(Qt.CursorShape.PointingHandCursor)
                    button.clicked.connect(lambda _checked=False, f=face: self.model.add(f))
                    self.suggestions_layout.addWidget(button)
        self._apply_suggestion_visibility()

    def _set_hint(self, text: str, tone: str, full: str | None = None) -> None:
        tint(self.hint_label, self._theme, tone)
        self.hint_label.set_text(text, full)

    def _apply_suggestion_visibility(self) -> None:
        """Show as many suggestion buttons as the tray's width allows (the third goes first, then the second)."""
        buttons = self.suggestion_buttons()
        width = self.width()
        shown = []
        for i, button in enumerate(buttons):
            visible = width >= SUGGESTION_MIN_WIDTHS[min(i, len(SUGGESTION_MIN_WIDTHS) - 1)]
            button.setVisible(visible)
            if visible:
                shown.append(button)
        self.suggestions_box.setVisible(bool(shown))
        natural = sum(b.sizeHint().width() for b in shown) + self.suggestions_layout.spacing() * max(len(shown) - 1, 0)
        self.suggestions_box.setMaximumWidth(natural)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_suggestion_visibility()

    # ----- widgets -> model -----
    def _schedule_order_sync(self) -> None:
        """Apply a drop's new order once the list has finished handling it (never mid-drop)."""
        if self._sync_pending:
            return
        self._sync_pending = True
        QTimer.singleShot(0, self._sync_order_from_list)

    def _sync_order_from_list(self) -> None:
        self._sync_pending = False
        if not self.model.set_order(self.list.keys()):
            self._rebuild_chips()  # a drop that changed nothing still drops the item widgets: put them back
