"""MaterialsTray: the always-visible strip at the bottom of the window.

Chips in priority order (drag to reorder, × to remove, "+ add"), a recap, a hint about what the sample
still needs (with "Add <family>" suggestions), and the Back / primary buttons. Everything the tray shows
comes from the ForgeModel; every action goes back through it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from fontplayground.engine.scripts import LABELS
from fontplayground.ui.model import ForgeModel

FaceKey = tuple[str, int]

MAX_SUGGESTIONS = 3
MAX_HINT_CHARS = 20            # missing characters shown in the hint before "…" (the tooltip has them all)
MIN_HEIGHT, MAX_HEIGHT = 64, 84
COLOR_MISSING, COLOR_OK, COLOR_NEUTRAL = "#b91c1c", "#15803d", "#4b5563"

STYLE = """
QWidget#tray { border-top: 1px solid #d3dae6; }
QListWidget#chips { background: transparent; border: none; }
QListWidget#chips::item { border: none; padding: 0; margin: 0; }
QListWidget#chips::item:selected, QListWidget#chips::item:hover { background: transparent; }
QFrame#chip { background: #eef1f5; border: 1px solid #d3dae6; border-radius: 13px; }
QFrame#chip[main="true"] { background: #e2ecff; border: 1px solid #7fa6f5; }
QLabel#chipText { background: transparent; border: none; color: #1f2933; }
QFrame#chip[main="true"] QLabel#chipText { color: #1d4ed8; font-weight: 600; }
QToolButton#chipClose { border: none; background: transparent; color: #6b7280; font-weight: bold; padding: 0 2px; }
QToolButton#chipClose:hover { color: #b91c1c; }
QPushButton#addButton { border: 1px dashed #9aa5b1; border-radius: 13px; background: transparent;
                        color: #4b5563; padding: 3px 12px; }
QPushButton#addButton:hover { border-color: #2563eb; color: #2563eb; }
QPushButton#suggest { border: 1px solid #f0b4b4; border-radius: 10px; background: #fff5f5; color: #b91c1c;
                      padding: 1px 8px; }
QPushButton#suggest:hover { background: #fee2e2; }
QLabel#recap { color: #4b5563; }
QPushButton#backButton { border: 1px solid #c8d0dc; border-radius: 6px; background: transparent; padding: 6px 12px; }
QPushButton#backButton:hover { background: #eef1f5; }
QPushButton#primaryButton { background: #2563eb; color: white; border: none; border-radius: 6px;
                            padding: 6px 16px; font-weight: 600; }
QPushButton#primaryButton:hover { background: #1d4ed8; }
QPushButton#primaryButton:disabled { background: #b7c7ea; color: #f8fafc; }
"""


def chip_label(rank: int, display_name: str) -> str:
    return f"{'Main' if rank == 0 else rank + 1} · {display_name}"


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

    def __init__(self, model: ForgeModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self._sync_pending = False
        self.setObjectName("tray")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
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

        info_row = QHBoxLayout()
        info_row.setSpacing(10)
        self.recap_label = QLabel("")
        self.recap_label.setObjectName("recap")
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("hint")
        self.suggestions_box = QWidget()
        self.suggestions_layout = QHBoxLayout(self.suggestions_box)
        self.suggestions_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestions_layout.setSpacing(4)
        info_row.addWidget(self.recap_label)
        info_row.addWidget(self.hint_label)
        info_row.addWidget(self.suggestions_box)
        info_row.addStretch(1)
        left.addLayout(info_row)
        root.addLayout(left, 1)

        self.back_button = QPushButton("‹ Back")
        self.back_button.setObjectName("backButton")
        self.primary_button = QPushButton("Next ›")
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.setCursor(Qt.CursorShape.PointingHandCursor)
        root.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.primary_button, 0, Qt.AlignmentFlag.AlignVCenter)

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
        self.primary_button.setText(text)
        self.primary_button.setEnabled(enabled)
        self.primary_button.setToolTip(tooltip)

    def set_back_visible(self, visible: bool) -> None:
        self.back_button.setVisible(visible)

    def chip_labels(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def chip_widget(self, i: int) -> Chip:
        return self.list.itemWidget(self.list.item(i))

    def suggestion_buttons(self) -> list[QPushButton]:
        return [self.suggestions_layout.itemAt(i).widget() for i in range(self.suggestions_layout.count())]

    # ----- model -> widgets -----
    def _on_materials_changed(self) -> None:
        self._rebuild_chips()
        self._refresh_recap()
        self._refresh_hint()

    def _on_plan_changed(self, _plan) -> None:
        self._refresh_recap()

    def _on_sample_changed(self, _text: str) -> None:
        self._refresh_hint()

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
                item.setSizeHint(chip.sizeHint())
                self.list.addItem(item)
                self.list.setItemWidget(item, chip)
        finally:
            self.list.blockSignals(False)

    def _refresh_recap(self) -> None:
        n = len(self.model.rows)
        chars = len(self.model.plan.source) if self.model.plan is not None else 0
        self.recap_label.setText(f"{n} {'font' if n == 1 else 'fonts'} · {chars:,} characters")

    def _refresh_hint(self) -> None:
        for button in self.suggestion_buttons():
            self.suggestions_layout.removeWidget(button)
            button.deleteLater()
        self.hint_label.setToolTip("")
        if not self.model.rows:
            self._set_hint("Pick a font to begin.", COLOR_NEUTRAL)
            return
        missing = self.model.missing_sample_chars()
        if not missing:
            self._set_hint("Your sample is fully covered.", COLOR_OK)
            return
        shown = " ".join(missing[:MAX_HINT_CHARS]) + (" …" if len(missing) > MAX_HINT_CHARS else "")
        self._set_hint(f"Your sample still needs: {shown}", COLOR_MISSING)
        self.hint_label.setToolTip(" ".join(missing))
        for face in self.model.suggestions(MAX_SUGGESTIONS):
            button = QPushButton(f"Add {face.family}")
            button.setObjectName("suggest")
            button.setToolTip(f"Add {face.display_name} to your materials")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, f=face: self.model.add(f))
            self.suggestions_layout.addWidget(button)

    def _set_hint(self, text: str, color: str) -> None:
        self.hint_label.setText(text)
        self.hint_label.setStyleSheet(f"color: {color};")

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
