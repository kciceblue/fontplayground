from dataclasses import replace

import pytest

from fontplayground.catalog.face import read_faces
from fontplayground.ui.languages import LANGUAGES
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.recipe import (ADD_TEXT, ANY_LANGUAGE_TEXT, LICENCE_TEXT, WEIGHT_CHOICES, FontCard,
                                      RecipePanel, family_styles, percent_scale, scale_percent, tally_language)
from fontplayground.ui.requests import PickRequest
from fontplayground.ui.theme import DARK, LIGHT
from tests.fixtures import cps, fake_face

WEIGHT_TEXTS = ["As is", "Light (300)", "Regular (400)", "Medium (500)", "Semibold (600)", "Bold (700)", "Heavy (900)"]


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    (c,) = read_faces(font_dir / "C.ttf")
    (v,) = read_faces(font_dir / "V.ttf")
    return a, b, c, v


@pytest.fixture
def model(qapp, faces):
    m = ForgeModel()
    m.set_catalog({f.key: f for f in faces})
    return m


@pytest.fixture
def panel(qtbot, model):
    p = RecipePanel(model)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def requests(panel):
    got: list[PickRequest] = []
    panel.chooseRequested.connect(got.append)
    return got


# ----- helpers -----------------------------------------------------------------------------------
def test_scale_and_weight_helpers():
    assert scale_percent(None) == 100 and scale_percent(1.2) == 120 and scale_percent(0.95) == 95
    assert percent_scale(100) is None and percent_scale(120) == 1.2
    assert [text for _w, text in WEIGHT_CHOICES] == WEIGHT_TEXTS
    assert [w for w, _text in WEIGHT_CHOICES] == [None, 300, 400, 500, 600, 700, 900]


def test_tally_language_prefers_the_largest_named_group_and_skips_symbols():
    assert tally_language({"han": 20000, "kana": 300, "cjk_symbols": 500}) == "chinese_s"
    assert tally_language({"symbols": 900, "greek": 60}) == "greek"      # symbols only when that is all
    assert tally_language({"symbols": 900, "emoji": 12}) == "symbols"
    assert tally_language({"hangul": 2000}) == "korean"
    assert tally_language({"other": 30}) == "any" and tally_language({}) == "any" and tally_language(None) == "any"


def test_family_styles_lists_supported_faces_of_the_family_lightest_first():
    regular = fake_face(cps("ab"), path="r.ttf", family="Fake", style="Regular", weight=400)
    bold = fake_face(cps("ab"), path="b.ttf", family="Fake", style="Bold", weight=700)
    light = fake_face(cps("ab"), path="l.ttf", family="Fake", style="Light", weight=300)
    bitmap = fake_face(cps("ab"), path="x.ttf", family="Fake", style="Black", weight=900, outline="none")
    other = fake_face(cps("ab"), path="o.ttf", family="Other", style="Regular")
    catalog = {f.key: f for f in (bold, regular, bitmap, other, light)}
    assert [f.style for f in family_styles(regular, catalog)] == ["Light", "Regular", "Bold"]
    lone = fake_face(cps("ab"), path="lone.ttf", family="Lone", style="Book")
    assert family_styles(lone, catalog) == [lone]          # not in the catalog: just itself


# ----- empty state -------------------------------------------------------------------------------
def test_empty_state_explains_the_two_steps(panel, requests):
    assert panel.objectName() == "recipe" and panel.title_label.text() == "Your font"
    assert panel.cards == []
    assert not panel.subtitle.isHidden()
    assert panel.subtitle.text() == "Combine installed fonts into one font that every app can use."
    assert not panel.step_main.isHidden() and not panel.step_more.isHidden()
    assert panel.step_main_title.text() == "Main font" and panel.step_main_badge.text() == "1"
    assert panel.step_main_text.text() == "The font you like for letters and numbers. It also sets the line spacing."
    assert panel.step_more_title.text() == "Fonts for other languages" and panel.step_more_badge.text() == "2"
    assert panel.step_more_text.text() == ("Chinese, Japanese, Korean… They fill in whatever the main font "
                                           "can't draw.")
    assert panel.choose_main_button.text() == "Choose main font…"
    assert panel.add_button.isHidden() and panel.prompt.isHidden()
    panel.choose_main_button.click()
    assert requests == [PickRequest("latin")]


def test_the_empty_state_goes_away_with_the_first_font_and_comes_back(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    assert len(panel.cards) == 1
    assert panel.subtitle.isHidden() and panel.step_main.isHidden() and panel.step_more.isHidden()
    assert not panel.add_button.isHidden() and panel.add_button.text() == ADD_TEXT
    model.reset()
    assert panel.cards == [] and not panel.step_main.isHidden() and panel.add_button.isHidden()


# ----- prompt ------------------------------------------------------------------------------------
def test_prompt_names_what_the_main_font_cannot_draw(panel, model, faces, requests):
    a, b, c, v = faces
    model.set_sample_text("ab 漢字 あ")
    assert panel.prompt.isHidden()                        # no font yet: the steps say it all
    model.add(a)
    assert not panel.prompt.isHidden()
    assert panel.prompt_label.text() == "Your text has Chinese and Japanese characters that Fixture A can't draw."
    assert panel.prompt_button.text() == "Choose a font for Chinese…"
    panel.prompt_button.click()
    assert requests == [PickRequest("chinese_s")]


def test_prompt_follows_the_sample_and_hides_with_two_fonts(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.set_sample_text("abc")
    assert panel.prompt.isHidden()                        # nothing missing
    model.set_sample_text("ab あ")
    assert not panel.prompt.isHidden() and panel.prompt_button.text() == "Choose a font for Japanese…"
    model.add(b)
    assert panel.prompt.isHidden()                        # two fonts: the missing note of the preview takes over
    model.remove(b.key)
    assert not panel.prompt.isHidden()


# ----- cards -------------------------------------------------------------------------------------
def test_cards_follow_the_model_order_and_are_updated_in_place(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    model.add(c)
    assert [card.key for card in panel.cards] == [a.key, b.key, c.key]
    assert all(isinstance(card, FontCard) for card in panel.cards)
    before = list(panel.cards)
    model.set_adjust(b.key, 700, 1.2)
    assert panel.cards == before and all(new is old for new, old in zip(panel.cards, before))
    assert panel.cards[1].size_spin.value() == 120 and panel.cards[1].weight_combo.currentText() == "Bold (700)"
    model.move(c.key, 0)
    assert [card.key for card in panel.cards] == [c.key, a.key, b.key]
    model.remove(a.key)
    assert [card.key for card in panel.cards] == [c.key, b.key]


def test_card_shows_the_family_in_its_own_font_and_the_native_name(panel, model, faces):
    a, b, c, v = faces
    native = replace(b, local_names=("汉字体", "漢字体"))
    model.set_catalog({**model.catalog, native.key: native})
    model.add(a)
    model.add(native)
    first, second = panel.cards
    assert first.name_label.text() == "Fixture A" and first.name_label.font().pointSizeF() == 17
    assert first.name_label.font().family() == "Fixture A"
    assert first.native_label.isHidden()
    assert second.name_label.text() == "Fixture B" and second.name_label.font().family() == "Fixture B"
    assert not second.native_label.isHidden() and second.native_label.text() == "汉字体"
    assert second.native_label.font().pointSizeF() == 12 and second.native_label.font().family() == "Fixture B"
    assert first.change_link.text() == "Change…" and first.menu_button.text() == "⋯"
    assert first.menu_button.menu() is first.menu


def test_name_line_gets_the_room_its_text_needs(qapp, panel, model, faces):
    a, b, c, v = faces
    native = replace(b, local_names=("汉字体",))
    model.set_catalog({**model.catalog, native.key: native})
    model.add(a)
    model.add(native)
    panel.resize(420, 800)
    panel.show()
    qapp.processEvents()
    for card in panel.cards:
        assert card.name_label.width() >= card.name_label.sizeHint().width() > 0
        assert card.name_label.elided_text() == card.name_label.text()
        assert card.name_label.x() < card.role_label.x() + 10           # left-aligned, not centred in its row
    native_label = panel.cards[1].native_label
    assert native_label.width() >= native_label.sizeHint().width() > 0


def test_first_card_has_no_size_or_weight(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    first, second = panel.cards
    assert first.adjust_row.isHidden() and not second.adjust_row.isHidden()
    assert [second.weight_combo.itemText(i) for i in range(second.weight_combo.count())] == WEIGHT_TEXTS
    assert second.size_spin.minimum() == 10 and second.size_spin.maximum() == 1000
    assert second.size_spin.suffix() == " %" and not second.size_spin.keyboardTracking()
    assert second.size_spin.value() == 100 and second.weight_combo.currentText() == "As is"


def test_roles_and_draws_follow_the_plan(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    first, second = panel.cards
    assert first.role_label.text() == "MAIN FONT"
    assert second.role_label.text() == "…" and second.draws_label.text() == "…"
    assert first.draws_label.text() == "… Sets the line spacing."
    model.recompute_plan_now()
    assert first.role_label.text() == "MAIN FONT"
    assert first.draws_label.text() == "Draws letters, numbers and punctuation. Sets the line spacing."
    assert second.role_label.text() == "FOR CHINESE"
    assert "Chinese characters" in second.draws_label.text()
    assert second.draws_label.text() == "Draws Chinese characters and CJK punctuation."
    assert second.draws_label.wordWrap()
    model.add(v)                                          # 'ab' only: everything it has is covered above
    model.add(c)                                          # Ω and →: Greek, with symbols
    model.recompute_plan_now()
    assert panel.cards[2].role_label.text() == "ADDS NOTHING"
    assert panel.cards[2].draws_label.text() == "Draws nothing — the fonts above already cover everything it has."
    assert panel.cards[3].role_label.text() == "FOR GREEK"


def test_line_spacing_sentence_follows_the_base(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    model.recompute_plan_now()
    first, second = panel.cards
    assert first.draws_label.text().endswith(" Sets the line spacing.")
    assert "line spacing" not in second.draws_label.text()
    model.set_base(b.key)                                 # in place, at once (the plan is not needed for it)
    assert panel.cards == [first, second]
    assert "line spacing" not in first.draws_label.text()
    assert second.draws_label.text() == "Draws Chinese characters and CJK punctuation. Sets the line spacing."
    model.recompute_plan_now()
    assert second.draws_label.text() == "Draws Chinese characters and CJK punctuation. Sets the line spacing."
    model.set_base(None)
    assert first.draws_label.text().endswith(" Sets the line spacing.")


def test_licence_line_only_for_restricted_embedding(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(c)
    assert c.embedding == "restricted"
    first, second = panel.cards
    assert first.licence_label.isHidden()
    assert not second.licence_label.isHidden() and second.licence_label.text() == LICENCE_TEXT
    assert LICENCE_TEXT == ("Its licence restricts embedding — fine for your own use; check before sharing the "
                            "result.")


def test_style_combo_lists_the_family_and_replaces_keeping_the_adjustments(panel, model, faces):
    a, b, c, v = faces
    regular = fake_face(cps("ab漢"), path="fake-r.ttf", family="Fake", style="Regular", weight=400)
    bold = fake_face(cps("ab漢"), path="fake-b.ttf", family="Fake", style="Bold", weight=700)
    other = fake_face(cps("ab"), path="other.ttf", family="Other", style="Medium", weight=500)
    model.set_catalog({f.key: f for f in (a, bold, regular, other)})
    model.add(a)
    model.add(regular)
    model.set_adjust(regular.key, 600, 1.1)
    card = panel.cards[1]
    combo = card.style_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Regular", "Bold"]
    assert combo.currentText() == "Regular"
    assert [panel.cards[0].style_combo.itemText(i) for i in range(panel.cards[0].style_combo.count())] == ["Regular"]
    combo.setCurrentIndex(1)
    assert model.keys() == [a.key, bold.key]
    assert (model.rows[1].weight, model.rows[1].scale) == (600, 1.1)
    new = panel.cards[1]
    assert new.key == bold.key and new.style_combo.currentText() == "Bold"
    assert new.size_spin.value() == 110 and new.weight_combo.currentText() == "Semibold (600)"


def test_size_and_weight_set_the_adjustment(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    card = panel.cards[1]
    card.size_spin.setValue(120)
    assert (model.rows[1].weight, model.rows[1].scale) == (None, 1.2)
    card.weight_combo.setCurrentIndex(5)                  # Bold (700); the size is kept
    assert (model.rows[1].weight, model.rows[1].scale) == (700, 1.2)
    card.size_spin.setValue(100)                          # 100 % = no size of its own
    assert (model.rows[1].weight, model.rows[1].scale) == (700, None)
    card.weight_combo.setCurrentIndex(0)                  # As is
    assert (model.rows[1].weight, model.rows[1].scale) == (None, None)
    assert panel.cards[1] is card


def test_a_stored_weight_outside_the_list_is_shown_as_its_number(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    model.set_adjust(b.key, 650, None)
    combo = panel.cards[1].weight_combo
    assert combo.currentText() == "650" and combo.count() == len(WEIGHT_TEXTS) + 1


def test_more_menu_actions_follow_the_position(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    model.add(c)
    first, middle, last = panel.cards
    texts = [act.text() for act in middle.menu.actions() if not act.isSeparator()]
    assert texts == ["Make main font", "Move up", "Move down", "Remove"]
    assert middle.menu.actions()[3].isSeparator()
    assert not first.make_main_action.isVisible() and not first.make_main_action.isEnabled()
    assert not first.move_up_action.isEnabled() and first.move_down_action.isEnabled()
    assert first.remove_action.isEnabled()
    assert middle.make_main_action.isVisible() and middle.make_main_action.isEnabled()
    assert middle.move_up_action.isEnabled() and middle.move_down_action.isEnabled()
    assert last.move_up_action.isEnabled() and not last.move_down_action.isEnabled()

    last.make_main_action.trigger()
    assert model.keys() == [c.key, a.key, b.key]
    panel.cards[1].move_down_action.trigger()
    assert model.keys() == [c.key, b.key, a.key]
    panel.cards[2].move_up_action.trigger()
    assert model.keys() == [c.key, a.key, b.key]
    panel.cards[0].remove_action.trigger()
    assert model.keys() == [a.key, b.key] and [card.key for card in panel.cards] == [a.key, b.key]


def test_change_asks_for_a_replacement_in_the_cards_language(panel, model, faces, requests):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    model.add(v)
    model.recompute_plan_now()
    for card in panel.cards:
        card.change_link.click()
    assert requests == [PickRequest("latin", replace_key=a.key), PickRequest("chinese_s", replace_key=b.key),
                        PickRequest("any", replace_key=v.key)]
    requests.clear()
    model.set_adjust(b.key, 700, None)                    # the plan is pending: the card's last share still counts
    panel.cards[1].change_link.click()
    assert requests == [PickRequest("chinese_s", replace_key=b.key)]


# ----- add menu, footer --------------------------------------------------------------------------
def test_add_menu_offers_every_language_then_any(panel, model, faces, requests):
    a, b, c, v = faces
    model.add(a)
    actions = panel.add_menu.actions()
    wanted = [lang for lang in LANGUAGES if lang.id != "any"]
    assert [act.data() for act in actions[:len(wanted)]] == [lang.id for lang in wanted]
    assert [act.text() for act in actions[:len(wanted)]] == [lang.label.replace("&", "&&") for lang in wanted]
    assert actions[len(wanted)].isSeparator()
    assert actions[-1].text() == ANY_LANGUAGE_TEXT == "Any language…" and actions[-1].data() == "any"
    assert len(actions) == len(wanted) + 2
    assert panel.add_button.menu() is panel.add_menu
    actions[3].trigger()                                  # Japanese
    actions[-1].trigger()
    assert requests == [PickRequest("japanese"), PickRequest("any")]


def test_advanced_link_asks_for_the_dialog(qtbot, panel):
    assert panel.advanced_link.text() == "Advanced…" and panel.advanced_hint.text() == "who draws what, line spacing"
    with qtbot.waitSignal(panel.advancedRequested, timeout=500):
        panel.advanced_link.click()


# ----- lock, theme -------------------------------------------------------------------------------
def _card_controls(card):
    return [card.style_combo, card.size_spin, card.weight_combo, card.change_link, card.menu_button]


def test_set_locked_disables_everything_that_changes_the_recipe(panel, model, faces):
    a, b, c, v = faces
    panel.set_locked(True)
    assert not panel.choose_main_button.isEnabled()
    model.add(a)                                          # cards built while locked are locked too
    model.set_sample_text("ab 漢")
    assert not panel.prompt.isHidden()
    assert not panel.prompt_button.isEnabled() and not panel.add_button.isEnabled()
    assert all(not w.isEnabled() for w in _card_controls(panel.cards[0]))
    assert panel.cards[0].role_label.text() == "MAIN FONT"   # the texts stay
    panel.set_locked(False)
    assert panel.prompt_button.isEnabled() and panel.add_button.isEnabled() and panel.choose_main_button.isEnabled()
    assert all(w.isEnabled() for w in _card_controls(panel.cards[0]))
    model.add(b)
    panel.set_locked(True)
    assert all(not w.isEnabled() for card in panel.cards for w in _card_controls(card))
    assert panel.advanced_link.isEnabled()


def test_apply_theme_rerenders_and_retints_the_dots(panel, model, faces):
    a, b, c, v = faces
    model.add(a)
    model.add(b)
    assert LIGHT.surface in panel.styleSheet()
    assert LIGHT.mix_colour(0) in panel.cards[0].dot.styleSheet()
    assert LIGHT.mix_colour(1) in panel.cards[1].dot.styleSheet()
    panel.apply_theme(DARK)
    assert DARK.surface in panel.styleSheet() and LIGHT.accent not in panel.styleSheet()
    assert DARK.mix_colour(0) in panel.cards[0].dot.styleSheet()
    assert DARK.mix_colour(1) in panel.cards[1].dot.styleSheet()
    model.add(c)                                          # rebuilt in the current theme
    assert DARK.mix_colour(2) in panel.cards[2].dot.styleSheet()


def test_panel_built_in_dark(qtbot, model, faces):
    a, b, c, v = faces
    model.add(a)
    p = RecipePanel(model, theme=DARK)
    qtbot.addWidget(p)
    assert DARK.surface in p.styleSheet() and DARK.mix_colour(0) in p.cards[0].dot.styleSheet()
