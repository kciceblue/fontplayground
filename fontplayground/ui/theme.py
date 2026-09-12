"""Colour tokens, the light and dark themes, and the manager that follows the system or the user's choice.

Every colour the UI shows comes from a Theme: page stylesheets are templates with `$token` placeholders
(rendered by Theme.render) and the application palette (Theme.palette) is built from the same tokens, so a
widget no stylesheet covers can never disagree with one that is styled.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QWidget

PREFERENCES = ("system", "light", "dark")
DEFAULT_PREFERENCE = "system"


@dataclass(frozen=True)
class Theme:
    name: str
    window: str                 # page background
    surface: str                # cards, tree, inputs, rail, status bar
    surface_alt: str            # badges, chips, hover fills
    surface_sunken: str         # main-window ground, details box
    border: str                 # card and input borders
    border_soft: str            # dividers, grid lines, disabled borders
    text: str
    text_secondary: str         # labels, recap, table text
    muted: str                  # hints, captions, placeholders
    faint: str                  # disabled text and borders
    accent: str                 # primary buttons, current step, links
    accent_hover: str
    accent_disabled: str
    accent_disabled_text: str
    accent_soft: str            # the "Main" chip
    accent_soft_border: str
    accent_soft_text: str
    on_accent: str              # text on accent
    ok: str
    ok_soft: str
    ok_soft_border: str
    danger: str
    danger_soft: str
    danger_soft_border: str
    danger_soft_hover: str
    warn_soft: str
    warn_border: str
    warn_text: str
    missing: str                # behind a character no font draws

    @property
    def tokens(self) -> dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "name"}

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"

    def render(self, template: str) -> str:
        """`template` with every `$token` replaced by this theme's colour; an unknown token raises KeyError."""
        return Template(template).substitute(self.tokens)

    def palette(self) -> QPalette:
        """The application palette for this theme, so unstyled widgets agree with the stylesheets."""
        Role, Group = QPalette.ColorRole, QPalette.ColorGroup
        colours = {
            Role.Window: self.window, Role.WindowText: self.text,
            Role.Base: self.surface, Role.AlternateBase: self.surface_alt, Role.Text: self.text,
            Role.Button: self.surface, Role.ButtonText: self.text,
            Role.ToolTipBase: self.surface, Role.ToolTipText: self.text,
            Role.PlaceholderText: self.muted,
            Role.Highlight: self.accent, Role.HighlightedText: self.on_accent,
            Role.Link: self.accent, Role.LinkVisited: self.accent,
            Role.Light: self.surface_alt, Role.Midlight: self.border_soft, Role.Mid: self.border,
            Role.Dark: self.border, Role.Shadow: self.border, Role.BrightText: self.on_accent,
        }
        palette = QPalette()
        for group in (Group.Active, Group.Inactive, Group.Disabled):
            for role, value in colours.items():
                palette.setColor(group, role, QColor(value))
        for role in (Role.Text, Role.WindowText, Role.ButtonText):
            palette.setColor(Group.Disabled, role, QColor(self.faint))
        palette.setColor(Group.Disabled, Role.Highlight, QColor(self.accent_disabled))
        palette.setColor(Group.Disabled, Role.HighlightedText, QColor(self.accent_disabled_text))
        return palette


LIGHT = Theme(
    name="light",
    window="#f4f6f9", surface="#ffffff", surface_alt="#eef1f5", surface_sunken="#fafafa",
    border="#d3dae6", border_soft="#e3e3e3",
    text="#1f2933", text_secondary="#4b5563", muted="#777777", faint="#c4c4c4",
    accent="#1a6bd8", accent_hover="#155bb8", accent_disabled="#b7c7ea", accent_disabled_text="#f8fafc",
    accent_soft="#e2ecff", accent_soft_border="#7fa6f5", accent_soft_text="#1d4ed8", on_accent="#ffffff",
    ok="#2f8f46", ok_soft="#e8f3ec", ok_soft_border="#bfe0c8",
    danger="#b3261e", danger_soft="#fff5f5", danger_soft_border="#f0b4b4", danger_soft_hover="#fee2e2",
    warn_soft="#fff6e0", warn_border="#f2c94c", warn_text="#7a4b00",
    missing="#ffb3b3",
)

DARK = Theme(
    name="dark",
    window="#1b1e24", surface="#262a31", surface_alt="#2f343c", surface_sunken="#1f2227",
    border="#3a404a", border_soft="#30353d",
    text="#e6e9ee", text_secondary="#b4bcc8", muted="#8b95a5", faint="#5b6370",
    accent="#4c8ef5", accent_hover="#6aa3ff", accent_disabled="#3a4a66", accent_disabled_text="#8a97ad",
    accent_soft="#1f2f4a", accent_soft_border="#3b5a8f", accent_soft_text="#9cc2ff", on_accent="#ffffff",
    ok="#5cc27a", ok_soft="#1d3327", ok_soft_border="#2f5a3d",
    danger="#ff7b72", danger_soft="#3a2224", danger_soft_border="#6b3a3a", danger_soft_hover="#4a2a2c",
    warn_soft="#3a3120", warn_border="#7a6a2a", warn_text="#f2c94c",
    missing="#7a2e2e",
)


# ----- helpers -----------------------------------------------------------------------------------
def _luminance(hex_colour: str) -> float:
    colour = QColor(hex_colour)

    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(colour.redF()) + 0.7152 * channel(colour.greenF()) + 0.0722 * channel(colour.blueF())


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast between two '#rrggbb' colours: 1 for identical colours, 21 for black on white."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def tint(widget: QWidget, theme: Theme, tone: str, extra_css: str = "") -> None:
    """Colour `widget`'s text with the token `tone`; the tone is kept on the widget so `retint` can redo it."""
    widget.setProperty("tone", tone)
    widget.setStyleSheet(f"color: {theme.tokens[tone]};" + (f" {extra_css}" if extra_css else ""))


def retint(widget: QWidget, theme: Theme, extra_css: str = "") -> None:
    """Re-apply the tone `tint` stored on `widget` with another theme (a widget never tinted is left alone)."""
    tone = widget.property("tone")
    if tone:
        tint(widget, theme, tone, extra_css)


def placeholder_html(theme: Theme, text: str = "Select a font to preview") -> str:
    """The muted 'nothing to show' line the preview boxes carry (here so preview and check page share it)."""
    return f'<span style="color:{theme.muted}">{text}</span>'


def system_theme() -> Theme:
    """DARK when the platform reports a dark colour scheme, else LIGHT (also when Qt cannot tell)."""
    return DARK if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT


# ----- manager -----------------------------------------------------------------------------------
class ThemeManager(QObject):
    """Resolves the user's preference (system / light / dark) to a Theme and pushes it to the application.

    `changed` carries the new Theme whenever the effective theme moves: the user picked another
    preference, or the system flipped while the preference is "system".
    """
    changed = Signal(object)   # Theme

    def __init__(self, preference: str = DEFAULT_PREFERENCE, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._preference = self._checked(preference)
        self._applying = False
        self._theme = self._push()
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_scheme_changed)

    @property
    def preference(self) -> str:
        return self._preference

    @preference.setter
    def preference(self, value: str) -> None:
        value = self._checked(value)
        if value == self._preference:
            return
        self._preference = value
        self.apply()

    @property
    def theme(self) -> Theme:
        return self._theme

    def apply(self) -> None:
        """Push the colour scheme and palette to the application; emit `changed` if the effective theme moved."""
        theme = self._push()
        if theme is not self._theme:
            self._theme = theme
            self.changed.emit(theme)

    @staticmethod
    def _checked(value: str) -> str:
        if value not in PREFERENCES:
            raise ValueError(f"Unknown theme preference {value!r}; expected one of {PREFERENCES}")
        return value

    def _push(self) -> Theme:
        hints = QGuiApplication.styleHints()
        self._applying = True   # setColorScheme re-emits colorSchemeChanged; that echo must not re-enter apply()
        try:
            if self._preference == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(Qt.ColorScheme.Dark if self._preference == "dark" else Qt.ColorScheme.Light)
        finally:
            self._applying = False
        if self._preference == "system":
            theme = system_theme()
        else:
            theme = DARK if self._preference == "dark" else LIGHT
        QGuiApplication.setPalette(theme.palette())
        return theme

    def _on_scheme_changed(self, _scheme) -> None:
        if not self._applying and self._preference == "system":
            self.apply()
