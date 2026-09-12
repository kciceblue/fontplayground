import re

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel

from fontplayground.ui import app, check_page, forge_page, pick_page, rail, tray
from fontplayground.ui.theme import (DARK, LIGHT, PREFERENCES, Theme, ThemeManager, contrast_ratio, placeholder_html,
                                     retint, system_theme, tint)

THEMES = [LIGHT, DARK]
TEMPLATES = {
    "app.APP_STYLE": app.APP_STYLE, "rail.STYLE": rail.STYLE, "pick_page.STYLE": pick_page.STYLE,
    "check_page.STYLE": check_page.STYLE, "forge_page.STYLE": forge_page.STYLE, "tray.STYLE": tray.STYLE,
}
HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")   # objectName selectors like #card never match
NAMED = re.compile(r"\b(white|black|gray|grey|red|green|blue)\b")
# (foreground, background, minimum WCAG ratio) — spec section 3
CONTRAST_RULE = [
    ("text", "surface", 4.5), ("text", "window", 4.5), ("text_secondary", "surface", 4.5),
    ("muted", "surface", 3.0), ("on_accent", "accent", 3.0), ("warn_text", "warn_soft", 3.0),
    ("ok", "ok_soft", 3.0), ("danger", "danger_soft", 3.0), ("text", "missing", 3.0),
]


def test_themes_have_the_same_lowercase_tokens():
    assert LIGHT.name == "light" and DARK.name == "dark" and DARK.is_dark and not LIGHT.is_dark
    assert set(LIGHT.tokens) == set(DARK.tokens) and "name" not in LIGHT.tokens
    for theme in THEMES:
        for token, value in theme.tokens.items():
            assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{theme.name}.{token} = {value!r}"


@pytest.mark.parametrize("name,template", TEMPLATES.items(), ids=list(TEMPLATES))
def test_templates_have_no_hardcoded_colours_and_render_in_both_themes(name, template):
    assert not HEX.search(template), f"{name} has a hex colour"
    assert not NAMED.search(template), f"{name} has a named colour"
    for theme in THEMES:
        rendered = theme.render(template)
        assert "$" not in rendered
        assert theme.surface in rendered or theme.accent in rendered or theme.muted in rendered


def test_placeholder_html_uses_the_muted_token():
    assert placeholder_html(DARK) == f'<span style="color:{DARK.muted}">Select a font to preview</span>'
    assert placeholder_html(LIGHT, "Nothing") == f'<span style="color:{LIGHT.muted}">Nothing</span>'


def test_render_rejects_an_unknown_token():
    with pytest.raises(KeyError):
        LIGHT.render("QLabel { color: $no_such_token; }")


def test_contrast_ratio_matches_wcag():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("theme", THEMES, ids=["light", "dark"])
def test_token_pairs_meet_the_contrast_rule(theme: Theme):
    for fg, bg, minimum in CONTRAST_RULE:
        ratio = contrast_ratio(theme.tokens[fg], theme.tokens[bg])
        assert ratio >= minimum, f"{theme.name}: {fg} on {bg} is {ratio:.2f}, needs {minimum}"


@pytest.mark.parametrize("theme", THEMES, ids=["light", "dark"])
def test_palette_comes_from_the_tokens(theme: Theme):
    p = theme.palette()
    Role, Group = QPalette.ColorRole, QPalette.ColorGroup
    for group in (Group.Active, Group.Inactive):
        assert p.color(group, Role.Window).name() == theme.window
        assert p.color(group, Role.WindowText).name() == theme.text
        assert p.color(group, Role.Base).name() == theme.surface
        assert p.color(group, Role.AlternateBase).name() == theme.surface_alt
        assert p.color(group, Role.Text).name() == theme.text
        assert p.color(group, Role.Button).name() == theme.surface
        assert p.color(group, Role.ButtonText).name() == theme.text
        assert p.color(group, Role.ToolTipBase).name() == theme.surface
        assert p.color(group, Role.ToolTipText).name() == theme.text
        assert p.color(group, Role.PlaceholderText).name() == theme.muted
        assert p.color(group, Role.Highlight).name() == theme.accent
        assert p.color(group, Role.HighlightedText).name() == theme.on_accent
        assert p.color(group, Role.Link).name() == theme.accent
        assert p.color(group, Role.Mid).name() == theme.border
        assert p.color(group, Role.Dark).name() == theme.border
        assert p.color(group, Role.Light).name() == theme.surface_alt
    for role in (Role.Text, Role.WindowText, Role.ButtonText):
        assert p.color(Group.Disabled, role).name() == theme.faint


def test_tint_and_retint(qtbot):
    label = QLabel("x")
    qtbot.addWidget(label)
    tint(label, LIGHT, "danger", "background: transparent;")
    assert label.styleSheet() == f"color: {LIGHT.danger}; background: transparent;"
    assert label.property("tone") == "danger"
    retint(label, DARK, "background: transparent;")
    assert label.styleSheet() == f"color: {DARK.danger}; background: transparent;"
    other = QLabel("y")
    qtbot.addWidget(other)
    retint(other, DARK)            # never tinted: nothing happens
    assert other.styleSheet() == ""


def test_manager_resolves_each_preference(qapp):
    assert PREFERENCES == ("system", "light", "dark")
    assert ThemeManager("light").theme is LIGHT
    assert ThemeManager("dark").theme is DARK
    assert qapp.palette().color(QPalette.ColorRole.Base).name() == DARK.surface   # pushed on construction
    m = ThemeManager("system")
    assert m.preference == "system" and m.theme is system_theme()
    with pytest.raises(ValueError):
        ThemeManager("blue")


def test_manager_emits_only_when_the_effective_theme_moves(qapp):
    m = ThemeManager("light")
    seen: list[Theme] = []
    m.changed.connect(seen.append)
    m.preference = "light"
    assert seen == []
    m.preference = "dark"
    assert seen == [DARK] and m.theme is DARK and m.preference == "dark"
    assert qapp.palette().color(QPalette.ColorRole.Base).name() == DARK.surface
    m.preference = "dark"
    assert seen == [DARK]
    with pytest.raises(ValueError):
        m.preference = "blue"
    assert m.preference == "dark"
    m.preference = "light"
    assert seen == [DARK, LIGHT] and qapp.palette().color(QPalette.ColorRole.Base).name() == LIGHT.surface
