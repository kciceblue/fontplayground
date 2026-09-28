"""The right side of the window: the preview, its toolbar, the trial banner and the note about missing characters.

The pane follows the model — the sample text and the recipe's mix — and hands the user's edits back to it. The
window tells it about a trial (the picker's candidate, with the banner that explains it) and about a built font.
Size and colour-by-font are the window's to store: preferencesChanged when the user changes them, set_preferences
to restore them without an echo.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSlider, QToolButton, QVBoxLayout, QWidget

from fontplayground.ui import languages
from fontplayground.ui.languages import ANY, SAMPLES
from fontplayground.ui.mix import Mix
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.preview import DEFAULT_POINT_SIZE, MixPreview
from fontplayground.ui.theme import LIGHT, Theme
from fontplayground.ui.widgets import ElidedLabel

MIN_POINT_SIZE, MAX_POINT_SIZE = 10, 96
MAX_LISTED = 12                   # missing characters named in the note before "and N more"
TITLE_TEXT = "Preview"
HINT_TEXT = "Click and type to try your own text"
COLOUR_TEXT = "Colour by font"
SIZE_TEXT = "Size"
SAMPLE_TEXT = "Sample ▾"
MORE_TEXT = "⋯"
FIND_TEXT = "Find a font…"

STYLE = """
QLabel#paneTitle { color: $text; font-size: 14px; font-weight: 600; background: transparent; }
QLabel#paneHint { color: $muted; background: transparent; }
QLabel#paneLabel { color: $text_secondary; background: transparent; }
QPushButton#chip { background: transparent; color: $text_secondary; border: 1px solid $border; border-radius: 12px;
                   padding: 3px 12px; }
QPushButton#chip:hover { background: $surface_alt; }
QPushButton#chip:checked { background: $accent_soft; border-color: $accent_soft_border; color: $accent_soft_text; }
QToolButton#sampleButton { background: transparent; color: $text_secondary; border: 1px solid $border;
                           border-radius: 6px; padding: 3px 10px; }
QToolButton#sampleButton:hover { background: $surface_alt; }
QToolButton#more { background: transparent; color: $text_secondary; border: none; border-radius: 6px;
                   font-size: 16px; padding: 0 6px; }
QToolButton#more:hover { background: $surface_alt; }
QToolButton#sampleButton::menu-indicator, QToolButton#more::menu-indicator { image: none; width: 0px; }
QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: $accent; width: 14px; margin: -6px 0; border-radius: 7px; }
QFrame#banner { background: $accent_soft; border: 1px solid $accent_soft_border; border-radius: 8px; }
QLabel#bannerText { color: $accent_soft_text; background: transparent; }
QFrame#notice { background: $warn_soft; border: 1px solid $warn_border; border-radius: 8px; }
QLabel#noticeText { color: $warn_text; background: transparent; }
QPushButton#noticeButton { background: transparent; color: $text_secondary; border: 1px solid $border;
                           border-radius: 6px; padding: 3px 10px; }
QPushButton#noticeButton:hover { background: $surface; }
"""


def missing_text(chars: list[str]) -> str:
    """The note's sentence: at most MAX_LISTED characters in quotes, then "and N more"; singular for one."""
    listed = ", ".join(f"“{c}”" for c in chars[:MAX_LISTED])
    if len(chars) > MAX_LISTED:
        listed += f" and {len(chars) - MAX_LISTED} more"
    if len(chars) == 1:
        return f"{listed} isn't in any of your fonts, so it would show as a box."
    return f"{listed} aren't in any of your fonts, so they would show as boxes."


def size_text(pt: int) -> str:
    return f"{pt} pt"


class PreviewPane(QWidget):
    addForLanguage = Signal(str)            # a languages id; "any" when the missing characters belong to none
    preferencesChanged = Signal(int, bool)  # point size, colour by font: the user changed one of them

    def __init__(self, model: ForgeModel, menu: QMenu | None = None, parent: QWidget | None = None,
                 theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.setObjectName("previewPane")
        self.model = model
        self._theme = theme
        self._missing_language = ANY          # what the note's button asks for

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        layout.addLayout(self._toolbar(menu))

        self.banner = QFrame()                 # shown while the picker tries a font
        self.banner.setObjectName("banner")
        self.banner_label = QLabel()
        self.banner_label.setObjectName("bannerText")
        self.banner_label.setWordWrap(True)
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(12, 8, 12, 8)
        banner_row.addWidget(self.banner_label, 1)
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        self.preview = MixPreview(theme=theme)
        layout.addWidget(self.preview, 1)

        self.missing_note = QFrame()           # shown while some visible character has no font
        self.missing_note.setObjectName("notice")
        self.missing_label = QLabel()
        self.missing_label.setObjectName("noticeText")
        self.missing_label.setWordWrap(True)
        self.missing_button = QPushButton()
        self.missing_button.setObjectName("noticeButton")
        self.missing_button.setCursor(Qt.CursorShape.PointingHandCursor)
        note_row = QHBoxLayout(self.missing_note)
        note_row.setContentsMargins(12, 8, 10, 8)
        note_row.setSpacing(10)
        note_row.addWidget(self.missing_label, 1)
        note_row.addWidget(self.missing_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.missing_note.setVisible(False)
        layout.addWidget(self.missing_note)

        self.apply_theme(theme)
        self.preview.shownChanged.connect(self._refresh_missing)
        self.preview.textEdited.connect(self._on_text_edited)
        self.missing_button.clicked.connect(self._on_missing_button)
        self.colour_button.toggled.connect(self._on_colour_toggled)
        self.size_slider.valueChanged.connect(self._on_size_changed)
        model.sampleChanged.connect(self._on_sample_changed)
        model.materialsChanged.connect(self._on_materials_changed)
        self.preview.set_text(model.sample_text)
        self.preview.set_mix(model.mix())

    def _toolbar(self, menu: QMenu | None) -> QHBoxLayout:
        self.title_label = QLabel(TITLE_TEXT)
        self.title_label.setObjectName("paneTitle")
        self.hint_label = ElidedLabel()        # gives way first when the window is narrow
        self.hint_label.setObjectName("paneHint")
        self.hint_label.set_text(HINT_TEXT)

        self.colour_button = QPushButton(COLOUR_TEXT)
        self.colour_button.setObjectName("chip")
        self.colour_button.setCheckable(True)
        self.colour_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.colour_button.setToolTip("Draw each font's characters in that font's colour")

        self.size_label = QLabel(SIZE_TEXT)
        self.size_label.setObjectName("paneLabel")
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(MIN_POINT_SIZE, MAX_POINT_SIZE)
        self.size_slider.setValue(DEFAULT_POINT_SIZE)
        self.size_slider.setFixedWidth(140)
        self.size_value = QLabel(size_text(DEFAULT_POINT_SIZE))
        self.size_value.setObjectName("paneLabel")
        self.size_value.setMinimumWidth(self.size_value.fontMetrics().horizontalAdvance(size_text(MAX_POINT_SIZE)))

        self.sample_menu = QMenu(self)
        for sample_id, (label, _text) in SAMPLES.items():
            self.sample_menu.addAction(label).setData(sample_id)
        self.sample_menu.triggered.connect(self._on_sample_chosen)
        self.sample_button = QToolButton()
        self.sample_button.setObjectName("sampleButton")
        self.sample_button.setText(SAMPLE_TEXT)
        self.sample_button.setToolTip("Replace the text with a sample (Ctrl+Z brings yours back)")
        self.sample_button.setMenu(self.sample_menu)
        self.sample_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sample_button.setCursor(Qt.CursorShape.PointingHandCursor)

        self.menu_button = QToolButton()
        self.menu_button.setObjectName("more")
        self.menu_button.setText(MORE_TEXT)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        if menu is not None:
            self.menu_button.setMenu(menu)
        self.menu_button.setVisible(menu is not None)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.title_label)
        row.addWidget(self.hint_label, 1)     # all it needs first (it is capped at its text's width)…
        row.addStretch(0)                     # …then whatever is left, so the controls stay packed on the right
        row.addWidget(self.colour_button)
        row.addSpacing(10)
        row.addWidget(self.size_label)
        row.addWidget(self.size_slider)
        row.addWidget(self.size_value)
        row.addSpacing(10)
        row.addWidget(self.sample_button)
        row.addWidget(self.menu_button)
        return row

    # ----- what the window tells the pane -----
    def set_trial(self, mix: Mix, banner_text: str) -> None:
        """Draw the picker's candidate mix, with the banner that says so, until clear_trial."""
        self.banner_label.setText(banner_text)
        self.banner.setVisible(True)
        self.preview.set_trial(mix)

    def clear_trial(self) -> None:
        self.banner.setVisible(False)
        self.preview.set_trial(None)

    def set_built(self, path: str, codepoints) -> None:
        """Draw the built font file (a trial still wins) until clear_built."""
        self.preview.set_built(path, codepoints)

    def clear_built(self) -> None:
        self.preview.set_built(None)

    def set_preferences(self, size: int, colour_by_font: bool) -> None:
        """Restore the stored size and colour-by-font; preferencesChanged is not emitted."""
        for control in (self.size_slider, self.colour_button):
            control.blockSignals(True)
        try:
            self.size_slider.setValue(int(size))          # clamped to the slider's range
            self.colour_button.setChecked(bool(colour_by_font))
        finally:
            for control in (self.size_slider, self.colour_button):
                control.blockSignals(False)
        self._show_size(self.size_slider.value())
        self.preview.set_colour_by_font(self.colour_button.isChecked())

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        self.preview.apply_theme(theme)

    # ----- reacting -----
    def _on_sample_changed(self, text: str) -> None:
        self.preview.set_text(text)

    def _on_materials_changed(self) -> None:
        self.preview.set_mix(self.model.mix())

    def _on_text_edited(self, text: str) -> None:
        self.model.set_sample_text(text)

    def _on_sample_chosen(self, action: QAction) -> None:
        _label, text = SAMPLES[action.data()]
        self.preview.replace_text(text)        # one undoable edit: Ctrl+Z restores the user's own text

    def _on_size_changed(self, value: int) -> None:
        self._show_size(value)
        self.preferencesChanged.emit(value, self.colour_button.isChecked())

    def _on_colour_toggled(self, on: bool) -> None:
        self.preview.set_colour_by_font(on)
        self.preferencesChanged.emit(self.size_slider.value(), on)

    def _show_size(self, value: int) -> None:
        self.size_value.setText(size_text(value))
        self.preview.set_point_size(value)

    def _on_missing_button(self) -> None:
        self.addForLanguage.emit(self._missing_language)

    def _refresh_missing(self) -> None:
        missing = self.preview.missing_characters()
        if missing:
            self.missing_label.setText(missing_text(missing))
            found = languages.languages_for_missing(missing)
            self._missing_language = found[0].id if found else ANY
            self.missing_button.setText(f"Add a font for {found[0].short_label}…" if found else FIND_TEXT)
        self.missing_note.setVisible(bool(missing))
