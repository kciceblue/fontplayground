"""PreviewPane: the toolbar, the trial banner, the preview and the note about characters no font draws."""
from PySide6.QtGui import QTextCursor, QTextFormat
from PySide6.QtWidgets import QMenu, QToolButton

from fontplayground.catalog.face import read_faces
from fontplayground.ui.languages import SAMPLES
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.preview_pane import PreviewPane, missing_text
from fontplayground.ui.theme import DARK, LIGHT


def _face(font_dir, name):
    (face,) = read_faces(font_dir / name)
    return face


def _pane(qtbot, model=None, menu=None) -> tuple[ForgeModel, PreviewPane]:
    model = model or ForgeModel()
    pane = PreviewPane(model, menu)
    qtbot.addWidget(pane)
    return model, pane


def _bg(fmt) -> str | None:
    return fmt.background().color().name() if fmt.hasProperty(QTextFormat.Property.BackgroundBrush) else None


def test_toolbar_has_its_controls_and_defaults(qtbot):
    _model, pane = _pane(qtbot)
    assert pane.title_label.text() == "Preview"
    assert pane.hint_label.text() == "Click and type to try your own text"
    assert pane.colour_button.text() == "Colour by font" and pane.colour_button.isCheckable()
    assert not pane.colour_button.isChecked()
    assert (pane.size_slider.minimum(), pane.size_slider.maximum(), pane.size_slider.value()) == (10, 96, 30)
    assert pane.size_value.text() == "30 pt"
    assert pane.sample_button.text() == "Sample ▾"
    assert pane.sample_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert pane.menu_button.isHidden()                 # no app menu given
    assert pane.banner.isHidden()
    assert pane.missing_note.isHidden()                # no fonts: nothing counts as missing


def test_the_app_menu_hangs_off_the_more_button(qtbot):
    menu = QMenu()
    _model, pane = _pane(qtbot, menu=menu)
    assert not pane.menu_button.isHidden()
    assert pane.menu_button.text() == "⋯" and pane.menu_button.menu() is menu
    assert pane.menu_button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup


def test_the_pane_starts_from_the_model_and_follows_it(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    model = ForgeModel()
    model.add(a)
    model.set_sample_text("ab")
    _model, pane = _pane(qtbot, model)
    assert pane.preview.text() == "ab" and pane.preview.shown_mix().keys() == [a.key]
    model.set_sample_text("ab漢")
    assert pane.preview.text() == "ab漢"
    assert not pane.missing_note.isHidden()
    model.add(b, "chinese_s")
    assert pane.preview.shown_mix().keys() == [a.key, b.key]
    assert pane.preview.source_at(2) == 1
    assert pane.missing_note.isHidden()
    pane.preview.moveCursor(QTextCursor.MoveOperation.End)
    qtbot.keyClicks(pane.preview, "1")
    assert model.sample_text == "ab漢1"


# ----- the missing note -------------------------------------------------------------------------------
def test_missing_note_is_hidden_when_everything_is_drawn(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    model.set_sample_text("abc 1,\n​")
    assert pane.missing_note.isHidden()
    model.set_sample_text("abc 한")
    assert not pane.missing_note.isHidden()
    model.set_sample_text("abc")
    assert pane.missing_note.isHidden()


def test_missing_note_lists_at_most_twelve_characters_then_a_count(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    model.set_sample_text("a 가나다라마바사아자차카타파하 가")
    listed = "“가”, “나”, “다”, “라”, “마”, “바”, “사”, “아”, “자”, “차”, “카”, “타”"
    assert not pane.missing_note.isHidden()
    assert pane.missing_label.text() == f"{listed} and 2 more aren't in any of your fonts, so they would show as boxes."
    assert pane.missing_label.wordWrap()
    assert pane.missing_button.text() == "Add a font for Korean…"
    with qtbot.waitSignal(pane.addForLanguage, timeout=1000) as blocker:
        pane.missing_button.click()
    assert blocker.args == ["korean"]


def test_missing_text_wording():
    assert missing_text(["한"]) == "“한” isn't in any of your fonts, so it would show as a box."
    assert missing_text(["안", "녕", "하"]) == "“안”, “녕”, “하” aren't in any of your fonts, so they would show as boxes."
    twelve = [chr(0xAC00 + i) for i in range(12)]
    assert "and" not in missing_text(twelve).split("aren't")[0]
    assert missing_text(twelve + ["x"]).startswith(", ".join(f"“{c}”" for c in twelve) + " and 1 more aren't")


def test_one_missing_character_is_singular(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    model.set_sample_text("a한")
    assert pane.missing_label.text() == "“한” isn't in any of your fonts, so it would show as a box."


def test_the_button_names_the_language_with_the_most_missing_characters(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    model.set_sample_text("a漢字한")
    assert pane.missing_button.text() == "Add a font for Chinese…"
    with qtbot.waitSignal(pane.addForLanguage, timeout=1000) as blocker:
        pane.missing_button.click()
    assert blocker.args == ["chinese_s"]


def test_characters_of_no_language_offer_to_find_any_font(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    model.set_sample_text("aሀ")                          # Ethiopic: no language of ours
    assert pane.missing_button.text() == "Find a font…"
    with qtbot.waitSignal(pane.addForLanguage, timeout=1000) as blocker:
        pane.missing_button.click()
    assert blocker.args == ["any"]


# ----- samples --------------------------------------------------------------------------------------
def test_sample_menu_replaces_the_text_as_one_undoable_edit(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    actions = pane.sample_button.menu().actions()
    assert [a.text() for a in actions] == [label for label, _text in SAMPLES.values()]
    model.set_sample_text("abc, cab 1")                # the user's own words, all drawn by Fixture A
    actions[list(SAMPLES).index("korean")].trigger()
    assert pane.preview.text() == SAMPLES["korean"][1] == model.sample_text
    assert not pane.missing_note.isHidden() and pane.missing_button.text() == "Add a font for Korean…"
    pane.preview.document().undo()                     # Ctrl+Z brings the user's words back, in the model too
    assert pane.preview.text() == "abc, cab 1" == model.sample_text
    assert pane.missing_note.isHidden()


# ----- preferences ----------------------------------------------------------------------------------
def test_size_and_colour_emit_preferences_and_set_preferences_does_not(qtbot):
    _model, pane = _pane(qtbot)
    seen: list[tuple[int, bool]] = []
    pane.preferencesChanged.connect(lambda size, colour: seen.append((size, colour)))
    pane.size_slider.setValue(40)
    assert seen == [(40, False)]
    assert pane.size_value.text() == "40 pt" and pane.preview.point_size() == 40
    pane.colour_button.click()
    assert seen[-1] == (40, True) and pane.preview.colour_by_font()
    seen.clear()
    pane.set_preferences(20, False)
    assert seen == []
    assert pane.size_slider.value() == 20 and pane.size_value.text() == "20 pt"
    assert not pane.colour_button.isChecked()
    assert pane.preview.point_size() == 20 and not pane.preview.colour_by_font()
    pane.set_preferences(64, True)
    assert seen == [] and pane.preview.colour_by_font() and pane.colour_button.isChecked()
    assert pane.preview.point_size() == 64 and pane.size_value.text() == "64 pt"


# ----- trial and built ------------------------------------------------------------------------------
def test_the_banner_shows_only_during_a_trial(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    model, pane = _pane(qtbot)
    model.add(a)
    model.set_sample_text("a漢")
    assert pane.banner.isHidden() and not pane.missing_note.isHidden()
    text = "Trying Fixture B for Chinese — ↑ ↓ try the next font, Enter uses it."
    pane.set_trial(model.mix_with(b, language="chinese_s"), text)
    assert not pane.banner.isHidden() and pane.banner_label.text() == text
    assert pane.preview.source_at(1) == 1
    assert pane.missing_note.isHidden()                # the candidate draws everything
    pane.clear_trial()
    assert pane.banner.isHidden()
    assert pane.preview.source_at(1) is None and not pane.missing_note.isHidden()


def test_the_built_font_shows_what_it_lacks(qtbot, font_dir):
    a, b = _face(font_dir, "A.ttf"), _face(font_dir, "B.otf")
    model, pane = _pane(qtbot)
    model.add(a)
    model.add(b)
    model.set_sample_text("ab漢")
    assert pane.missing_note.isHidden()
    pane.set_built(a.path, a.codepoints)
    assert not pane.missing_note.isHidden()
    assert pane.missing_label.text() == "“漢” isn't in any of your fonts, so it would show as a box."
    pane.clear_built()
    assert pane.missing_note.isHidden()


# ----- theme ----------------------------------------------------------------------------------------
def test_apply_theme_recolours_the_pane_and_the_preview(qtbot, font_dir):
    model, pane = _pane(qtbot)
    model.add(_face(font_dir, "A.ttf"))
    model.set_sample_text("a漢")
    assert _bg(pane.preview.format_at(1)) == LIGHT.missing
    assert LIGHT.warn_soft in pane.styleSheet()
    pane.apply_theme(DARK)
    assert _bg(pane.preview.format_at(1)) == DARK.missing
    assert DARK.warn_soft in pane.styleSheet() and LIGHT.warn_soft not in pane.styleSheet()
