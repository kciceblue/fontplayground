"""The recipe: the left column that says which fonts make up the user's font ("Your font").

Empty, it explains the two steps (a main font, then fonts for other languages). With fonts, it shows one card per
font in priority order: its colour-by-font dot, its role ("MAIN FONT", "FOR CHINESE"), its name drawn in the font
itself, its style (and, below the main font, size and weight) and what it draws in the plan. With exactly one font
and sample characters it cannot draw, a prompt names the language to add next. Nothing here keeps state of its
own: every card reads the ForgeModel and every action goes back through it; choosing a font is asked of the main
window with a PickRequest (chooseRequested). While a build runs the app locks the panel (set_locked).
"""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QToolButton, QVBoxLayout, QWidget)

from fontplayground.catalog.face import FontFace
from fontplayground.engine.scripts import GROUP_IDS
from fontplayground.ui import languages
from fontplayground.ui.fonts import face_font
from fontplayground.ui.languages import ANY, LANGUAGES, LATIN, Language
from fontplayground.ui.model import ForgeModel, MaterialRow
from fontplayground.ui.requests import PickRequest
from fontplayground.ui.theme import LIGHT, Theme
from fontplayground.ui.widgets import ElidedLabel

FaceKey = tuple[str, int]

TITLE_TEXT = "Your font"
SUBTITLE_TEXT = "Combine installed fonts into one font that every app can use."
MAIN_STEP_TITLE = "Main font"
MAIN_STEP_TEXT = "The font you like for letters and numbers. It also sets the line spacing."
CHOOSE_MAIN_TEXT = "Choose main font…"
MORE_STEP_TITLE = "Fonts for other languages"
MORE_STEP_TEXT = "Chinese, Japanese, Korean… They fill in whatever the main font can't draw."
MAIN_ROLE = "MAIN FONT"
PENDING = "…"                          # role and draws lines until the plan has caught up
LINE_SPACING_TEXT = "Sets the line spacing."
LICENCE_TEXT = "Its licence restricts embedding — fine for your own use; check before sharing the result."
CHANGE_TEXT = "Change…"
MORE_TEXT = "⋯"
MAKE_MAIN_TEXT = "Make main font"
MOVE_UP_TEXT = "Move up"
MOVE_DOWN_TEXT = "Move down"
REMOVE_TEXT = "Remove"
ADD_TEXT = "＋  Add a font for another language…"
ANY_LANGUAGE_TEXT = "Any language…"
ADVANCED_TEXT = "Advanced…"
ADVANCED_HINT = "who draws what, line spacing"
NAME_PT, NATIVE_PT = 17, 12            # the family name and its native name, drawn in the font itself
SCALE_RANGE = (10, 1000)               # percent
WEIGHT_CHOICES: tuple[tuple[int | None, str], ...] = (
    (None, "As is"), (300, "Light (300)"), (400, "Regular (400)"), (500, "Medium (500)"),
    (600, "Semibold (600)"), (700, "Bold (700)"), (900, "Heavy (900)"),
)

STYLE = """
QWidget#recipe { background: $surface; }
QScrollArea#recipeScroll { background: transparent; border: none; }
QScrollArea#recipeScroll > QWidget#qt_scrollarea_viewport, QWidget#recipeBody { background: transparent; }
QLabel { color: $text; background: transparent; }
QLabel#h1 { font-size: 18px; font-weight: 600; }
QLabel#h2 { font-size: 14px; font-weight: 600; }
QLabel#muted { color: $muted; }
QLabel#secondary { color: $text_secondary; }
QLabel#role { color: $muted; font-size: 11px; font-weight: 700; }
QLabel#draws { color: $text_secondary; }
QLabel#licence { color: $warn_text; }
QLabel#step { background: $surface_alt; color: $text_secondary; border-radius: 11px; font-weight: 700;
              min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }
QLabel#stepOn { background: $accent; color: $on_accent; border-radius: 11px; font-weight: 700;
                min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px; }
QFrame#card { background: $surface_alt; border: 1px solid $border; border-radius: 10px; }
QFrame#stepMain { background: transparent; border: 1px dashed $border; border-radius: 10px; }
QFrame#stepMore { background: transparent; border: 1px dashed $border_soft; border-radius: 10px; }
QFrame#stepMore QLabel#h2 { color: $muted; }
QFrame#prompt { background: $accent_soft; border: 1px solid $accent_soft_border; border-radius: 10px; }
QLabel#promptText { color: $accent_soft_text; }
QPushButton#primary { background: $accent; color: $on_accent; border: none; border-radius: 8px; padding: 8px 18px;
                      font-weight: 600; }
QPushButton#primary:hover { background: $accent_hover; }
QPushButton#primary:disabled { background: $accent_disabled; color: $accent_disabled_text; }
QPushButton#link { background: transparent; border: none; color: $accent; padding: 0 2px; }
QPushButton#link:hover { color: $accent_hover; text-decoration: underline; }
QPushButton#link:disabled { color: $faint; }
QPushButton#addButton { background: transparent; border: 1px dashed $faint; border-radius: 10px; padding: 11px 14px;
                        color: $text_secondary; text-align: left; }
QPushButton#addButton:hover { border-color: $accent; color: $accent; }
QPushButton#addButton:disabled { border-color: $border_soft; color: $faint; }
QPushButton#addButton::menu-indicator { image: none; width: 0; }
QToolButton#more { background: transparent; border: none; color: $text_secondary; font-size: 16px; padding: 0 6px; }
QToolButton#more:hover { color: $accent; }
QToolButton#more:disabled { color: $faint; }
QToolButton#more::menu-indicator { image: none; width: 0; }
QComboBox, QSpinBox { background: $surface; color: $text; border: 1px solid $border; border-radius: 6px;
                      padding: 3px 8px; }
QComboBox:disabled, QSpinBox:disabled { color: $faint; border-color: $border_soft; }
"""


# ----- small helpers (pure) -----------------------------------------------------------------------
def scale_percent(scale: float | None) -> int:
    """Model scale -> spin value (None, "no size of its own", is 100 %)."""
    return 100 if scale is None else round(scale * 100)


def percent_scale(percent: int) -> float | None:
    """Spin value -> model scale; 100 % means no size of its own (None)."""
    return None if percent == 100 else percent / 100


def mnemonic_safe(text: str) -> str:
    """Button and menu texts treat '&' as a shortcut marker: 'Armenian & Georgian' must show its '&'."""
    return text.replace("&", "&&")


def fill_weight_combo(combo: QComboBox) -> None:
    """The weight choices ("As is", "Light (300)" … "Heavy (900)"), each with its weight (None for As is) as data."""
    for weight, text in WEIGHT_CHOICES:
        combo.addItem(text, weight)


def select_weight(combo: QComboBox, weight: int | None) -> None:
    """Show `weight` in a combo filled by fill_weight_combo; a weight outside the list is added as its number."""
    i = next((i for i in range(combo.count()) if combo.itemData(i) == weight), -1)
    if i < 0:  # a value outside the usual steps (from a settings file): show it anyway
        combo.addItem(str(weight), weight)
        i = combo.count() - 1
    if combo.currentIndex() != i:
        combo.setCurrentIndex(i)


def family_styles(face: FontFace, catalog: Mapping[FaceKey, FontFace]) -> list[FontFace]:
    """The supported faces of the face's family in the catalog, lightest first (just the face when it is not there).

    One face per style name: when a family is installed twice, the face in the recipe (else the first found) wins.
    """
    by_style: dict[str, FontFace] = {}
    for f in catalog.values():
        if f.family == face.family and f.supported and f.style not in by_style:
            by_style[f.style] = f
    by_style[face.style] = face
    return sorted(by_style.values(), key=lambda f: (f.weight_class, f.italic, f.style))


def tally_language(tally: Mapping[str, int] | None) -> str:
    """The language id a (non-main) font's share of the plan is for: that of its largest group worth naming,
    symbols only when that is all it draws; ANY when nothing points to a language (like role_title)."""
    if not tally:
        return ANY
    total = sum(tally.values())
    ranked = sorted((g for g, n in tally.items() if n > 0), key=lambda g: (-tally[g], GROUP_IDS.index(g)))
    ranked = [g for i, g in enumerate(ranked) if i == 0 or tally[g] >= languages.MIN_SHARE * total]
    ids = [languages.GROUP_LANGUAGE[g] for g in ranked if g in languages.GROUP_LANGUAGE]
    named = [i for i in ids if i != "symbols"] or ids
    return named[0] if named else ANY


def prompt_text(langs: list[Language], family: str) -> str:
    return f"Your text has {languages.join_labels(langs)} characters that {family} can't draw."


def prompt_button_text(lang: Language) -> str:
    return f"Choose a font for {lang.short_label}…"


def _label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _button(text: str, name: str) -> QPushButton:
    button = QPushButton(mnemonic_safe(text))
    button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _step_badge(text: str, name: str) -> QLabel:
    badge = _label(text, name)
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return badge


# ----- one font --------------------------------------------------------------------------------------
class FontCard(QFrame):
    """One font of the recipe: dot, role, Change…, ⋯, name in its own font, style (size, weight) and its share.

    A card lives as long as its font keeps its place: the panel rebuilds every card when the fonts or their order
    change, so `index` and `count` never change; everything else is updated in place (update_from, set_tally,
    set_base). The card never touches the model: it asks the panel through its signals.
    """
    styleChosen = Signal(object, object)       # key, FontFace (another style of the family)
    weightChosen = Signal(object, object)      # key, weight | None
    scaleChosen = Signal(object, object)       # key, scale | None
    moveRequested = Signal(object, int)        # key, new index
    removeRequested = Signal(object)           # key
    changeRequested = Signal(object)           # key

    def __init__(self, row: MaterialRow, index: int, count: int, catalog: Mapping[FaceKey, FontFace],
                 parent: QWidget | None = None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.key: FaceKey = row.face.key
        self.face: FontFace = row.face
        self.index = index
        self.count = count
        self.tally: dict[str, int] | None = None     # its share of the last plan, per script group
        self._body = PENDING                         # the "Draws …" sentence without the line-spacing one
        self._is_base = False
        self._locked = False
        self._styles: list[FontFace] = []
        self._styles_from: tuple[object, FontFace] | None = None   # (catalog, face) the style list was made from
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 12)
        layout.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.dot = QLabel("●")
        self.dot.setObjectName("dot")
        self.role_label = _label(MAIN_ROLE if index == 0 else PENDING, "role")
        self.change_link = _button(CHANGE_TEXT, "link")
        self.change_link.setToolTip("Use another font in its place")
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("more")
        self.menu_button.setText(MORE_TEXT)
        self.menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self.menu_button)
        self.make_main_action = self.menu.addAction(MAKE_MAIN_TEXT)
        self.move_up_action = self.menu.addAction(MOVE_UP_TEXT)
        self.move_down_action = self.menu.addAction(MOVE_DOWN_TEXT)
        self.menu.addSeparator()
        self.remove_action = self.menu.addAction(REMOVE_TEXT)
        self.menu_button.setMenu(self.menu)
        head.addWidget(self.dot)
        head.addWidget(self.role_label)
        head.addStretch(1)
        head.addWidget(self.change_link)
        head.addWidget(self.menu_button)
        layout.addLayout(head)

        # Both names get the width of their text while there is room and shrink (elided) past the card's width;
        # the stretch after them keeps the row left-aligned.
        names = QHBoxLayout()
        names.setSpacing(10)
        self.name_label = ElidedLabel()
        self.native_label = ElidedLabel()
        self.native_label.setObjectName("muted")
        for label in (self.name_label, self.native_label):
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(1)
            names.addWidget(label)
        names.addStretch(1)
        layout.addLayout(names)

        style_row = QHBoxLayout()
        style_row.setSpacing(6)
        self.style_combo = QComboBox()
        self.style_combo.setMinimumWidth(120)
        self.style_combo.setToolTip("Another style of the same family")
        style_row.addWidget(_label("Style", "secondary"))
        style_row.addWidget(self.style_combo)
        style_row.addStretch(1)
        layout.addLayout(style_row)

        self.adjust_row = QWidget()        # size and weight: not on the main font (it sets the size of the rest)
        adjust = QHBoxLayout(self.adjust_row)
        adjust.setContentsMargins(0, 0, 0, 0)
        adjust.setSpacing(6)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(*SCALE_RANGE)
        self.size_spin.setSuffix(" %")
        self.size_spin.setValue(100)
        self.size_spin.setKeyboardTracking(False)
        self.size_spin.setMinimumWidth(84)
        self.size_spin.setToolTip("Draw this font's characters larger or smaller (100 % keeps them as they are)")
        self.weight_combo = QComboBox()
        fill_weight_combo(self.weight_combo)
        self.weight_combo.setMinimumWidth(110)
        self.weight_combo.setToolTip("Make this font bolder or lighter ('As is' keeps it unchanged)")
        adjust.addWidget(_label("Size", "secondary"))
        adjust.addWidget(self.size_spin)
        adjust.addSpacing(14)
        adjust.addWidget(_label("Weight", "secondary"))
        adjust.addWidget(self.weight_combo)
        adjust.addStretch(1)
        self.adjust_row.setVisible(index > 0)
        layout.addWidget(self.adjust_row)

        self.draws_label = _label(PENDING, "draws", wrap=True)
        self.licence_label = _label(LICENCE_TEXT, "licence", wrap=True)
        layout.addWidget(self.draws_label)
        layout.addWidget(self.licence_label)

        self._show_face(row.face)
        self._fill_styles(catalog)
        self._show_adjust(row.weight, row.scale)
        self._apply_enabled()
        self.apply_theme(theme)

        self.style_combo.currentIndexChanged.connect(self._on_style_chosen)
        self.size_spin.valueChanged.connect(self._on_size_changed)
        self.weight_combo.currentIndexChanged.connect(self._on_weight_chosen)
        self.change_link.clicked.connect(self._on_change_clicked)
        self.make_main_action.triggered.connect(self._on_make_main)
        self.move_up_action.triggered.connect(self._on_move_up)
        self.move_down_action.triggered.connect(self._on_move_down)
        self.remove_action.triggered.connect(self._on_remove)

    # ----- model -> card -----
    def update_from(self, row: MaterialRow, catalog: Mapping[FaceKey, FontFace]) -> None:
        """Refresh the face (a rescan may bring a new one under the same key), the styles, size and weight."""
        if row.face != self.face:
            self._show_face(row.face)
        self._fill_styles(catalog)
        self._show_adjust(row.weight, row.scale)

    def set_tally(self, tally: Mapping[str, int] | None) -> None:
        """Its share of the plan (characters per group): the role and draws lines; None while the plan is pending."""
        self.tally = dict(tally) if tally is not None else None
        if self.index > 0:
            self.role_label.setText(languages.role_title(tally) if tally is not None else PENDING)
        self._body = languages.draws_text(tally) if tally is not None else PENDING
        self._show_draws()

    def set_base(self, is_base: bool) -> None:
        """Whether the result takes its line spacing from this font (said at the end of the draws line)."""
        if is_base != self._is_base:
            self._is_base = is_base
            self._show_draws()

    def set_locked(self, locked: bool) -> None:
        """A build is running: every control is off (the texts stay)."""
        self._locked = bool(locked)
        self._apply_enabled()

    def apply_theme(self, theme: Theme) -> None:
        self.dot.setStyleSheet(f"color: {theme.mix_colour(self.index)}; font-size: 13px;")

    # ----- internals -----
    def _show_face(self, face: FontFace) -> None:
        self.face = face
        self.name_label.setFont(face_font(face, NAME_PT))
        self.name_label.set_text(face.family)
        native = face.local_names[0] if face.local_names else ""
        self.native_label.setFont(face_font(face, NATIVE_PT))
        self.native_label.set_text(native)
        self.native_label.setVisible(bool(native))
        self.licence_label.setVisible(face.embedding == "restricted")

    def _fill_styles(self, catalog: Mapping[FaceKey, FontFace]) -> None:
        if self._styles_from is not None and self._styles_from[0] is catalog and self._styles_from[1] == self.face:
            return  # the same catalog and face: the list cannot have changed
        self._styles_from = (catalog, self.face)
        styles = family_styles(self.face, catalog)
        current = next(i for i, f in enumerate(styles) if f.key == self.face.key)
        self.style_combo.blockSignals(True)
        try:
            if [f.key for f in styles] != [f.key for f in self._styles]:
                self.style_combo.clear()
                for i, f in enumerate(styles):
                    self.style_combo.addItem(f.style)
                    self.style_combo.setItemData(i, f.display_name, Qt.ItemDataRole.ToolTipRole)
                self._styles = styles
            self.style_combo.setCurrentIndex(current)
        finally:
            self.style_combo.blockSignals(False)

    def _show_adjust(self, weight: int | None, scale: float | None) -> None:
        self.weight_combo.blockSignals(True)
        self.size_spin.blockSignals(True)
        try:
            select_weight(self.weight_combo, weight)
            percent = scale_percent(scale)
            if self.size_spin.value() != percent:   # never rewrite a spin box that already shows the value
                self.size_spin.setValue(percent)
        finally:
            self.weight_combo.blockSignals(False)
            self.size_spin.blockSignals(False)

    def _show_draws(self) -> None:
        self.draws_label.setText(f"{self._body} {LINE_SPACING_TEXT}" if self._is_base else self._body)

    def _apply_enabled(self) -> None:
        on = not self._locked
        for widget in (self.style_combo, self.size_spin, self.weight_combo, self.change_link, self.menu_button):
            widget.setEnabled(on)
        first, last = self.index == 0, self.index == self.count - 1
        self.make_main_action.setVisible(not first)
        self.make_main_action.setEnabled(not first)
        self.move_up_action.setEnabled(not first)
        self.move_down_action.setEnabled(not last)

    # ----- card -> panel -----
    def _on_style_chosen(self, index: int) -> None:
        if 0 <= index < len(self._styles) and self._styles[index].key != self.key:
            self.styleChosen.emit(self.key, self._styles[index])

    def _on_size_changed(self, percent: int) -> None:
        self.scaleChosen.emit(self.key, percent_scale(percent))

    def _on_weight_chosen(self, index: int) -> None:
        if index >= 0:
            self.weightChosen.emit(self.key, self.weight_combo.itemData(index))

    def _on_change_clicked(self) -> None:
        self.changeRequested.emit(self.key)

    def _on_make_main(self) -> None:
        self.moveRequested.emit(self.key, 0)

    def _on_move_up(self) -> None:
        self.moveRequested.emit(self.key, self.index - 1)

    def _on_move_down(self) -> None:
        self.moveRequested.emit(self.key, self.index + 1)

    def _on_remove(self) -> None:
        self.removeRequested.emit(self.key)


# ----- the column --------------------------------------------------------------------------------------
class RecipePanel(QWidget):
    """"Your font": the two steps when empty, else the cards, the next-step prompt and the add button."""
    chooseRequested = Signal(object)      # PickRequest: open the picker for it
    advancedRequested = Signal()

    def __init__(self, model: ForgeModel, parent: QWidget | None = None, theme: Theme = LIGHT) -> None:
        super().__init__(parent)
        self.model = model
        self.cards: list[FontCard] = []
        self._locked = False
        self._theme = theme
        self._prompt_language = ANY
        self.setObjectName("recipe")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        self.title_label = _label(TITLE_TEXT, "h1")
        outer.addWidget(self.title_label)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("recipeScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("recipeBody")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)

        # ----- empty state -----
        self.subtitle = _label(SUBTITLE_TEXT, "muted", wrap=True)
        column.addWidget(self.subtitle)
        self.step_main = QFrame()
        self.step_main.setObjectName("stepMain")
        main_layout = QVBoxLayout(self.step_main)
        main_layout.setContentsMargins(16, 14, 16, 16)
        main_layout.setSpacing(8)
        self.step_main_badge = _step_badge("1", "stepOn")
        self.step_main_title = _label(MAIN_STEP_TITLE, "h2")
        self.step_main_text = _label(MAIN_STEP_TEXT, "secondary", wrap=True)
        self.choose_main_button = _button(CHOOSE_MAIN_TEXT, "primary")
        main_layout.addLayout(self._row(self.step_main_badge, self.step_main_title))
        main_layout.addWidget(self.step_main_text)
        main_layout.addLayout(self._row(self.choose_main_button))
        column.addWidget(self.step_main)
        self.step_more = QFrame()
        self.step_more.setObjectName("stepMore")
        more_layout = QVBoxLayout(self.step_more)
        more_layout.setContentsMargins(16, 14, 16, 16)
        more_layout.setSpacing(8)
        self.step_more_badge = _step_badge("2", "step")
        self.step_more_title = _label(MORE_STEP_TITLE, "h2")
        self.step_more_text = _label(MORE_STEP_TEXT, "muted", wrap=True)
        more_layout.addLayout(self._row(self.step_more_badge, self.step_more_title))
        more_layout.addWidget(self.step_more_text)
        column.addWidget(self.step_more)

        # ----- cards, prompt, add -----
        self.cards_box = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_box)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        column.addWidget(self.cards_box)
        self.prompt = QFrame()
        self.prompt.setObjectName("prompt")
        prompt_layout = QVBoxLayout(self.prompt)
        prompt_layout.setContentsMargins(14, 12, 14, 14)
        prompt_layout.setSpacing(8)
        self.prompt_label = _label("", "promptText", wrap=True)
        self.prompt_button = _button("", "primary")
        prompt_layout.addWidget(self.prompt_label)
        prompt_layout.addLayout(self._row(self.prompt_button))
        column.addWidget(self.prompt)
        self.add_button = _button(ADD_TEXT, "addButton")
        self.add_menu = QMenu(self.add_button)
        for lang in LANGUAGES:
            if lang.id != ANY:
                self.add_menu.addAction(mnemonic_safe(lang.label)).setData(lang.id)
        self.add_menu.addSeparator()
        self.add_menu.addAction(ANY_LANGUAGE_TEXT).setData(ANY)
        self.add_button.setMenu(self.add_menu)
        column.addWidget(self.add_button)
        column.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)

        # ----- footer -----
        self.advanced_link = _button(ADVANCED_TEXT, "link")
        self.advanced_hint = _label(ADVANCED_HINT, "muted")
        footer = self._row(self.advanced_link, self.advanced_hint)
        footer.setSpacing(6)
        outer.addLayout(footer)

        # ----- wiring (bound methods: Qt drops them cleanly if the panel dies before the model) -----
        self.choose_main_button.clicked.connect(self._on_choose_main)
        self.prompt_button.clicked.connect(self._on_prompt_clicked)
        self.add_menu.triggered.connect(self._on_add_chosen)
        self.advanced_link.clicked.connect(self._on_advanced_clicked)
        self.model.materialsChanged.connect(self._on_materials_changed)
        self.model.planChanged.connect(self._on_plan_changed)
        self.model.sampleChanged.connect(self._on_sample_changed)
        self.setStyleSheet(theme.render(STYLE))
        self.refresh()

    # ----- public API -----
    def refresh(self) -> None:
        """Rebuild everything from the model."""
        self._on_materials_changed()

    def set_locked(self, locked: bool) -> None:
        """While a build runs nothing here may change the recipe: cards, Change…, ⋯, add, prompt, choose main."""
        self._locked = bool(locked)
        for card in self.cards:
            card.set_locked(self._locked)
        for widget in (self.choose_main_button, self.prompt_button, self.add_button):
            widget.setEnabled(not self._locked)

    def is_locked(self) -> bool:
        return self._locked

    def apply_theme(self, theme: Theme) -> None:
        """Re-render the sheet and re-tint every card's dot."""
        self._theme = theme
        self.setStyleSheet(theme.render(STYLE))
        for card in self.cards:
            card.apply_theme(theme)

    # ----- model -> widgets -----
    def _on_materials_changed(self) -> None:
        rows = self.model.rows
        if [c.key for c in self.cards] != [r.face.key for r in rows]:
            self._rebuild_cards(rows)
        else:
            catalog = self.model.catalog
            for card, row in zip(self.cards, rows):
                card.update_from(row, catalog)
        empty = not rows
        for widget in (self.subtitle, self.step_main, self.step_more):
            widget.setVisible(empty)
        self.add_button.setVisible(not empty)
        tallies = self.model.tallies()
        if tallies is not None:       # otherwise the cards keep their last share until the plan catches up
            self._show_tallies(tallies)
        base = self.model.base_index()
        for i, card in enumerate(self.cards):
            card.set_base(i == base)
        self._refresh_prompt()

    def _on_plan_changed(self, _plan) -> None:
        self._show_tallies(self.model.tallies())
        self._refresh_prompt()

    def _on_sample_changed(self, _text: str) -> None:
        self._refresh_prompt()

    def _show_tallies(self, tallies: list[dict[str, int]] | None) -> None:
        for i, card in enumerate(self.cards):
            card.set_tally(tallies[i] if tallies is not None and i < len(tallies) else None)

    def _rebuild_cards(self, rows: list[MaterialRow]) -> None:
        for card in self.cards:
            self.cards_layout.removeWidget(card)
            card.hide()
            card.deleteLater()     # it may be the sender (a style chosen, Remove): Qt deletes it after the signal
        self.cards = []
        catalog = self.model.catalog
        for i, row in enumerate(rows):
            card = FontCard(row, i, len(rows), catalog, theme=self._theme)
            card.set_locked(self._locked)
            card.styleChosen.connect(self._on_style_chosen)
            card.weightChosen.connect(self._on_weight_chosen)
            card.scaleChosen.connect(self._on_scale_chosen)
            card.moveRequested.connect(self._on_move_requested)
            card.removeRequested.connect(self._on_remove_requested)
            card.changeRequested.connect(self._on_change_requested)
            self.cards_layout.addWidget(card)
            self.cards.append(card)

    def _refresh_prompt(self) -> None:
        """The next-step prompt: exactly one font, and sample characters it cannot draw that point to a language."""
        rows = self.model.rows
        langs = languages.languages_for_missing(self.model.missing_sample_chars()) if len(rows) == 1 else []
        if langs:
            self._prompt_language = langs[0].id
            self.prompt_label.setText(prompt_text(langs, rows[0].face.family))
            self.prompt_button.setText(mnemonic_safe(prompt_button_text(langs[0])))
        self.prompt.setVisible(bool(langs))

    # ----- widgets -> model / main window -----
    def _on_choose_main(self) -> None:
        self.chooseRequested.emit(PickRequest(LATIN))

    def _on_advanced_clicked(self) -> None:
        self.advancedRequested.emit()

    def _on_prompt_clicked(self) -> None:
        self.chooseRequested.emit(PickRequest(self._prompt_language))

    def _on_add_chosen(self, action) -> None:
        language_id = action.data()
        if isinstance(language_id, str):
            self.chooseRequested.emit(PickRequest(language_id))

    def _on_change_requested(self, key: FaceKey) -> None:
        """Change… asks for a replacement among the fonts for the card's language (Latin for the main font)."""
        i = self.model.index_of(key)
        if i is None:
            return
        if i == 0:
            language_id = LATIN
        else:
            tallies = self.model.tallies()
            tally = tallies[i] if tallies is not None and i < len(tallies) else self.cards[i].tally
            language_id = tally_language(tally)
        self.chooseRequested.emit(PickRequest(language_id, replace_key=key))

    def _on_style_chosen(self, key: FaceKey, face: FontFace) -> None:
        self.model.replace(key, face, keep_adjust=True)

    def _on_weight_chosen(self, key: FaceKey, weight: int | None) -> None:
        row = self.model.row(key)
        if row is not None:
            self.model.set_adjust(key, weight, row.scale)

    def _on_scale_chosen(self, key: FaceKey, scale: float | None) -> None:
        row = self.model.row(key)
        if row is not None:
            self.model.set_adjust(key, row.weight, scale)

    def _on_move_requested(self, key: FaceKey, index: int) -> None:
        self.model.move(key, index)

    def _on_remove_requested(self, key: FaceKey) -> None:
        self.model.remove(key)

    @staticmethod
    def _row(*widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for widget in widgets:
            row.addWidget(widget)
        row.addStretch(1)
        return row
