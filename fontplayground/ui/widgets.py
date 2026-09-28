"""Small widgets and helpers the panels share (rescued from the old tray and Check page)."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QStyle, QStyleOption, QToolButton, QWidget


def restyle(widget: QWidget) -> None:
    """Re-apply the stylesheet after a property the sheet selects on has changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_flag(widget: QWidget, name: str, value) -> None:
    """Set a dynamic property the stylesheet selects on (`QLabel[main="true"]`), restyling only when it changed."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        restyle(widget)


def elide_middle(text: str, limit: int) -> str:
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


class Disclosure(QToolButton):
    """A '▸ Details' / '▾ Details' button that shows or hides one body widget (hidden to start with)."""

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
