"""The step rail: "1 Pick fonts › 2 Check › 3 Forge & save", a subtitle for the current step, and the ⋯ menu."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QMenu, QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

STEP_TITLES = ("1  Pick fonts", "2  Check", "3  Forge & save")
STEP_SUBTITLES = (
    "Pick the font whose letters you like first; the others fill in what it lacks.",
    "See which font draws what. Drag chips in the tray to change the order.",
    "Name it, look at it, save or install it.",
)
DONE_MARK = "✓ "
SEPARATOR = "›"

STYLE = """
QWidget#rail { background: #ffffff; border-bottom: 1px solid #e3e3e3; }
QToolButton#step { background: transparent; border: none; border-bottom: 3px solid transparent;
                   color: #8a8a8a; font-size: 14px; padding: 6px 14px; }
QToolButton#step:hover { color: #444444; }
QToolButton#step[done="true"] { color: #2f8f46; }
QToolButton#step:disabled { color: #c4c4c4; }
QToolButton#step:checked { color: #1a6bd8; font-weight: 600; border-bottom: 3px solid #1a6bd8; }
QLabel#separator { color: #b0b0b0; font-size: 14px; padding: 6px 0; }
QLabel#subtitle { color: #666666; font-size: 12px; padding: 0 14px 6px 14px; }
QToolButton#overflow { background: transparent; border: none; border-radius: 4px; font-size: 16px; padding: 2px 8px; }
QToolButton#overflow:hover { background: #f0f0f0; }
QToolButton#overflow::menu-indicator { image: none; }
"""


def done_title(title: str) -> str:
    """'1  Pick fonts' -> '✓  Pick fonts': the check replaces the step number."""
    text = title.split("  ", 1)[1] if "  " in title else title
    return DONE_MARK + " " + text


def button_text(title: str) -> str:
    """What to hand QToolButton.setText: a lone '&' would become a shortcut marker, so it is doubled."""
    return title.replace("&", "&&")


class StepRail(QWidget):
    stepClicked = Signal(int)   # 0-based; only for reachable steps

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self._step = 0
        self._reachable = [True] + [False] * (len(STEP_TITLES) - 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 0)
        outer.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QToolButton] = []
        self.separators: list[QLabel] = []
        for i, title in enumerate(STEP_TITLES):
            button = QToolButton()
            button.setObjectName("step")
            button.setText(button_text(title))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.group.addButton(button, i)
            self.buttons.append(button)
            row.addWidget(button)
            if i < len(STEP_TITLES) - 1:
                sep = QLabel(SEPARATOR)
                sep.setObjectName("separator")
                self.separators.append(sep)
                row.addWidget(sep)
        row.addStretch(1)

        self.menu_button = QToolButton()
        self.menu_button.setObjectName("overflow")
        self.menu_button.setText("⋯")
        self.menu_button.setToolTip("More")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu = QMenu(self.menu_button)
        self.rescan_action = QAction("Rescan fonts", self)
        self.add_folder_action = QAction("Add folder…", self)
        self.start_over_action = QAction("Start over", self)
        self.open_settings_action = QAction("Open settings folder", self)
        self.menu.addAction(self.rescan_action)
        self.menu.addAction(self.add_folder_action)
        self.menu.addSeparator()
        self.menu.addAction(self.start_over_action)
        self.menu.addSeparator()
        self.menu.addAction(self.open_settings_action)
        self.menu_button.setMenu(self.menu)
        row.addWidget(self.menu_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(row)

        self.subtitles: list[QLabel] = []
        self.subtitle_stack = QStackedWidget()
        for text in STEP_SUBTITLES:
            label = QLabel(text)
            label.setObjectName("subtitle")
            label.setWordWrap(True)
            self.subtitles.append(label)
            self.subtitle_stack.addWidget(label)
        outer.addWidget(self.subtitle_stack)

        self.group.idClicked.connect(self._on_clicked)
        self.set_step(0)

    # ----- public API -----
    def step(self) -> int:
        return self._step

    def set_step(self, index: int) -> None:
        """Make step `index` (0-based) the current one; every step up to it counts as reachable."""
        if not 0 <= index < len(self.buttons):
            raise IndexError(f"No step {index}")
        self._step = index
        for i in range(index + 1):
            self._reachable[i] = True
        self.buttons[index].setChecked(True)
        self.subtitle_stack.setCurrentIndex(index)
        self._restyle()

    def set_reachable(self, index: int, reachable: bool) -> None:
        """Allow (or grey out) jumping to a step. The current step and completed steps stay reachable."""
        if not 0 <= index < len(self.buttons):
            raise IndexError(f"No step {index}")
        self._reachable[index] = bool(reachable) or index <= self._step
        self._restyle()

    def is_reachable(self, index: int) -> bool:
        return self._reachable[index]

    def subtitle(self) -> str:
        return self.subtitles[self._step].text()

    # ----- internals -----
    def _on_clicked(self, index: int) -> None:
        if not self._reachable[index]:
            self.buttons[self._step].setChecked(True)  # nothing changes
            return
        if index != self._step:
            self.set_step(index)
        self.stepClicked.emit(index)

    def _restyle(self) -> None:
        for i, (button, title) in enumerate(zip(self.buttons, STEP_TITLES)):
            done = i < self._step
            button.setText(button_text(done_title(title) if done else title))
            button.setEnabled(self._reachable[i])
            button.setToolTip("" if self._reachable[i] else "Finish the earlier steps first")
            if button.property("done") != done:
                button.setProperty("done", done)
                button.style().unpolish(button)
                button.style().polish(button)
