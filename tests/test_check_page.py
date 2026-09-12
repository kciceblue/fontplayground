import os
from pathlib import Path

import pytest

from PySide6.QtGui import QFont

from fontplayground.catalog.face import read_faces
from fontplayground.engine.scripts import GROUP_IDS, GROUPS, LABELS
from fontplayground.engine.spec import ForgeReport
from fontplayground.ui import workers
from fontplayground.ui.check_page import (ADDS_NOTHING_TEXT, ADJUST_TEXT, AS_IS, COL_COUNTS, COL_SUPPLIER,
                                          LINE_SPACING_BADGE, MAX_MISSING_CHARS, MISSING_PREFIX, NO_COUNT, NOBODY,
                                          PENDING_TEXT, PLACEHOLDER_TEXT, SAMPLE_LINE, SAMPLE_PT, SHOW_ALL_TEXT,
                                          SHOW_COVERED_TEXT, WEIGHT_CHOICES, CheckPage, MaterialCard, adjust_title,
                                          plan_line, sample_wght, short_names)
from fontplayground.ui.model import ForgeModel, MaterialRow
from fontplayground.ui.preview import PreviewWidget
from fontplayground.ui.theme import DARK, LIGHT
from tests.fixtures import cps, fake_face

# one character per script group, in GROUPS order (Ethiopic ሀ falls into "Everything else")
ONE_PER_GROUP = "aΩжԱאاनกあ한漢，→😀ሀ"


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    (v,) = read_faces(font_dir / "V.ttf")
    return a, b, v


@pytest.fixture
def model(qapp, faces):
    m = ForgeModel()
    m.set_catalog({f.key: f for f in faces})
    return m


def _page(qtbot, model) -> CheckPage:
    page = CheckPage(model, PreviewWidget(sizes=(12,)))
    qtbot.addWidget(page)
    page.show()
    return page


@pytest.fixture
def page_ab(qtbot, model, faces):
    """A (Latin) then B (Han + Latin) in the model, the plan computed, and a page on top."""
    a, b, v = faces
    model.add(a)
    model.add(b)
    page = _page(qtbot, model)
    model.recompute_plan_now()
    return page


@pytest.fixture
def quick_fake_forge(monkeypatch):
    """A forge() that writes a stub result at once, so a test can have a result without a real combine."""
    def fake_forge(spec, output_path, progress=None):
        Path(output_path).write_bytes(b"stub")
        return ForgeReport([], 0, 0, [], str(output_path))
    monkeypatch.setattr(workers, "forge", fake_forge)


def _fragments(doc):
    """(text, family, point size, background colour name or None) for every fragment, in order."""
    out = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            fmt = frag.charFormat()
            colour = fmt.background().color().name() if fmt.hasProperty(fmt.Property.BackgroundBrush) else None
            out.append((frag.text(), fmt.font().family(), fmt.font().pointSize(), colour))
            it += 1
        block = block.next()
    return out


def _red_chars(doc, colour: str = LIGHT.missing) -> set[str]:
    return {ch for text, _, _, c in _fragments(doc) if c == colour for ch in text}


def _cleanup_result(model: ForgeModel) -> None:
    path = model.result_path
    model.discard_result()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ----- helpers -----------------------------------------------------------------------------------
def test_plan_line_names_the_biggest_groups_with_thousands_separators():
    han = set(range(0x4E00, 0x4E00 + 1200))
    kana = cps("あいう")
    latin = cps("ab")
    assert plan_line(han | kana | latin) == "supplies Han 1,200 · Kana 3 · Latin 2 (1,205 characters)"
    assert plan_line(cps("a")) == "supplies Latin 1 (1 character)"
    many = han | kana | latin | cps("Ω") | cps("ж")   # five groups: only three are named
    assert plan_line(many) == "supplies Han 1,200 · Kana 3 · Latin 2 · … (1,207 characters)"


def test_short_names_use_the_family_unless_two_materials_share_it():
    a = fake_face(cps("a"), path="a.ttf", family="Segoe UI", style="Regular")
    b = fake_face(cps("b"), path="b.ttf", family="YaHei", style="Regular")
    b2 = fake_face(cps("c"), path="b2.ttf", family="YaHei", style="Bold")
    assert short_names([a, b]) == {a.key: "Segoe UI", b.key: "YaHei"}
    assert short_names([a, b, b2]) == {a.key: "Segoe UI", b.key: "YaHei Regular", b2.key: "YaHei Bold"}


# ----- cards -------------------------------------------------------------------------------------
def test_empty_model_shows_the_placeholder_card(qtbot, model):
    page = _page(qtbot, model)
    assert page.cards == [] and not page.placeholder.isHidden()
    assert page.placeholder_label.text() == PLACEHOLDER_TEXT == "No fonts yet — go back to Pick fonts."
    assert page.table.rowCount() == 0 and page.missing_label.isHidden()
    assert page.base_combo.count() == 1 and not page.base_combo.isEnabled()
    assert page.preview.in_plan_mode() and page.preview.current_family() is None


def test_cards_follow_the_model_in_priority_order(page_ab, model, faces):
    a, b, v = faces
    page = page_ab
    assert page.placeholder.isHidden()
    assert [c.key for c in page.cards] == [a.key, b.key] and all(isinstance(c, MaterialCard) for c in page.cards)
    first, second = page.cards
    assert first.rank_badge.text() == "Main" and first.rank_badge.property("main") is True
    assert second.rank_badge.text() == "2" and second.rank_badge.property("main") is False
    assert first.name_label.text() == "Fixture A Regular" and first.name_label.font().bold()
    assert second.name_label.text() == "Fixture B Bold" and second.name_label.font().bold()
    assert not first.base_badge.isHidden() and first.base_badge.text() == LINE_SPACING_BADGE == "line spacing"
    assert second.base_badge.isHidden()
    assert not first.up_button.isEnabled() and first.down_button.isEnabled()
    assert second.up_button.isEnabled() and not second.down_button.isEnabled()
    assert first.adjust_area.isHidden() and not first.adjust_button.isChecked()
    first.adjust_button.setChecked(True)
    assert not first.adjust_area.isHidden()
    model.remove(a.key)
    assert [c.key for c in page.cards] == [b.key] and page.cards[0].rank_badge.text() == "Main"
    assert not page.cards[0].base_badge.isHidden()
    model.remove(b.key)
    assert page.cards == [] and not page.placeholder.isHidden()


def test_sample_lines_are_drawn_in_each_font_with_red_for_what_it_lacks(page_ab, faces):
    a_card, b_card = page_ab.cards
    for card, family in ((a_card, "Fixture A"), (b_card, "Fixture B")):
        frags = _fragments(card.sample.document())
        assert "".join(t for t, *_ in frags) == SAMPLE_LINE == "Aa Ëé Ωж 漢あ한 ①"
        assert {f for _, f, _, _ in frags} == {family}
        assert {size for _, _, size, _ in frags} == {SAMPLE_PT} == {16}
        assert card.sample.isReadOnly() and card.sample.document().defaultFont().family() == family
    assert "漢" in _red_chars(a_card.sample.document()) and "a" not in _red_chars(a_card.sample.document())
    assert "①" in _red_chars(b_card.sample.document()) and "漢" not in _red_chars(b_card.sample.document())
    assert " " not in _red_chars(a_card.sample.document())   # spaces are never marked


def test_plan_lines_summarise_each_share(qtbot, model, faces):
    a, b, v = faces
    model.add(a)
    model.add(b)
    page = _page(qtbot, model)                       # no plan yet: the lines wait for it
    assert [c.plan_label.text() for c in page.cards] == [PENDING_TEXT, PENDING_TEXT]
    model.recompute_plan_now()
    a_card, b_card = page.cards
    assert a_card.plan_label.text() == "supplies Latin 5 (5 characters)" and not a_card.plan_label.isHidden()
    assert "Han" in b_card.plan_label.text()
    assert b_card.plan_label.text() == "supplies Han 1 · CJK symbols & fullwidth 1 (2 characters)"
    assert a_card.nothing_badge.isHidden() and b_card.nothing_badge.isHidden()

    model.add(v)                                     # 'ab' only: everything it has is already covered above
    model.recompute_plan_now()
    v_card = page.cards[2]
    assert v_card.plan_label.isHidden() and not v_card.nothing_badge.isHidden()
    assert v_card.nothing_badge.text() == ADDS_NOTHING_TEXT
    model.move(v.key, 0)                             # as Main it keeps the Latin it has (a tenth of A's is enough)
    assert [c.plan_label.text() for c in page.cards] == [PENDING_TEXT] * 3   # rebuilt: the lines wait again
    model.recompute_plan_now()
    assert page.cards[0].key == v.key
    assert page.cards[0].plan_label.text() == "supplies Latin 2 (2 characters)" and page.cards[0].nothing_badge.isHidden()
    assert page.cards[1].plan_label.text() == "supplies Latin 3 (3 characters)"
    model.set_pin("latin", a.key)                    # asked for explicitly: A draws all the Latin, V has no share
    model.recompute_plan_now()
    assert page.cards[0].plan_label.isHidden() and not page.cards[0].nothing_badge.isHidden()
    assert page.cards[1].plan_label.text() == "supplies Latin 5 (5 characters)"


def test_move_buttons_reorder_the_model_and_rebuild_the_cards(qtbot, page_ab, model, faces):
    a, b, v = faces
    page = page_ab
    old_cards = list(page.cards)
    page.cards[0].down_button.click()
    assert model.keys() == [b.key, a.key]
    assert [c.key for c in page.cards] == [b.key, a.key]
    assert all(new is not old for new in page.cards for old in old_cards)   # rebuilt, not relabelled
    assert page.cards[0].rank_badge.text() == "Main" and page.cards[1].rank_badge.text() == "2"
    assert not page.cards[0].base_badge.isHidden() and page.cards[1].base_badge.isHidden()
    page.cards[1].up_button.click()
    assert model.keys() == [a.key, b.key] and [c.key for c in page.cards] == [a.key, b.key]
    assert page.base_combo.count() == 3 and page.base_combo.itemText(1) == "Fixture A Regular"


# ----- table -------------------------------------------------------------------------------------
def test_table_lists_only_covered_groups_until_show_all(page_ab, faces):
    page = page_ab
    groups = page.table_groups()
    assert page.table.rowCount() == len(groups) == 3
    assert groups == ["latin", "han", "cjk_symbols"] and "arabic" not in groups
    assert [page.table.item(r, 0).text() for r in range(3)] == ["Latin", "Han", "CJK symbols & fullwidth"]
    assert [page.table.horizontalHeaderItem(c).text() for c in range(3)] == ["Script", "Supplied by", "Characters"]
    assert page.cell_text("han", COL_COUNTS) == "Fixture B 1"
    assert page.cell_text("latin", COL_COUNTS) == "Fixture A 5 · Fixture B 2"
    assert page.supplier_combo("han").currentText() == "Auto → Fixture B Bold"
    latin = page.supplier_combo("latin")
    assert [latin.itemText(i) for i in range(latin.count())] == ["Auto → Fixture A Regular", "Fixture A Regular",
                                                                  "Fixture B Bold"]

    assert page.show_all_button.text() == SHOW_ALL_TEXT == "Show all 15 scripts"
    page.show_all_button.click()
    assert page.show_all_button.isChecked() and page.show_all_button.text() == SHOW_COVERED_TEXT
    assert page.table.rowCount() == len(GROUPS) == 15 and page.table_groups() == [g.id for g in GROUPS]
    assert page.cell_text("arabic", COL_SUPPLIER) == NOBODY == "nobody"
    assert page.cell_text("arabic", COL_COUNTS) == NO_COUNT == "—"
    assert page.supplier_combo("arabic") is None and page.supplier_combo("han") is not None
    assert page.table.item(page.table_row("arabic"), 0).text() == LABELS["arabic"] == "Arabic"
    page.show_all_button.click()
    assert page.table.rowCount() == 3 and page.table_groups() == ["latin", "han", "cjk_symbols"]


def test_choosing_a_supplier_pins_it_and_the_preview_follows(qtbot, page_ab, model, faces):
    a, b, v = faces
    page = page_ab
    model.set_sample_text("a")
    assert page.preview.sample_text() == "a"
    assert _fragments(page.preview.browsers[0].document())[0][1] == "Fixture A"
    assert model.pins["latin"] is None
    page.supplier_combo("latin").setCurrentIndex(2)   # Fixture B Bold
    assert model.pins["latin"] == b.key
    model.recompute_plan_now()
    assert page.supplier_combo("latin").currentIndex() == 2
    assert page.supplier_combo("latin").currentText() == "Fixture B Bold"
    assert page.cell_text("latin", COL_COUNTS) == "Fixture B 2 · Fixture A 5"   # the supplier comes first
    assert _fragments(page.preview.browsers[0].document())[0][1] == "Fixture B"
    assert model.script_rules()["latin"] == 1

    page.supplier_combo("latin").setCurrentIndex(0)   # back to Auto
    assert model.pins["latin"] is None
    model.recompute_plan_now()
    assert page.cell_text("latin", COL_COUNTS) == "Fixture A 5 · Fixture B 2"
    assert _fragments(page.preview.browsers[0].document())[0][1] == "Fixture A"


def test_pins_set_on_the_model_show_in_the_table(page_ab, model, faces):
    a, b, v = faces
    model.set_pin("han", a.key)                       # A cannot draw Han, but the pin is what the user asked for
    assert page_ab.supplier_combo("han").currentIndex() == 1
    model.remove(a.key)
    assert page_ab.supplier_combo("han").currentIndex() == 0 and model.pins["han"] is None


# ----- adjust ------------------------------------------------------------------------------------
def test_boldness_and_size_write_through_and_make_the_result_stale(qtbot, page_ab, model, faces, quick_fake_forge):
    a, b, v = faces
    page = page_ab
    a_card = page.cards[0]
    assert [a_card.weight_combo.itemText(i) for i in range(a_card.weight_combo.count())] == WEIGHT_CHOICES
    assert a_card.weight_combo.currentText() == AS_IS and a_card.scale_spin.value() == 100
    assert (a_card.scale_spin.minimum(), a_card.scale_spin.maximum()) == (10, 1000)
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        assert model.combine()
    try:
        assert model.result_path is not None and not model.is_stale
        with qtbot.waitSignal(model.resultStale):
            a_card.weight_combo.setCurrentText("700")
        assert model.row(a.key).weight == 700 and model.row(a.key).scale is None
        assert model.is_stale
        assert page.cards[0] is a_card                 # same keys: the card was refreshed in place, not rebuilt
        a_card.scale_spin.setValue(150)
        assert (model.row(a.key).weight, model.row(a.key).scale) == (700, 1.5)
        a_card.scale_spin.setValue(100)                # 100 % means "no adjustment"
        assert model.row(a.key).scale is None
        a_card.weight_combo.setCurrentText(AS_IS)
        assert model.row(a.key).weight is None
    finally:
        _cleanup_result(model)


def test_adjustments_made_on_the_model_reach_the_card(page_ab, model, faces):
    a, b, v = faces
    b_card = page_ab.cards[1]
    model.set_adjust(b.key, 300, 0.8)
    assert b_card.weight_combo.currentText() == "300" and b_card.scale_spin.value() == 80
    model.set_adjust(b.key, 650, None)                # not one of the usual steps: shown anyway
    assert b_card.weight_combo.currentText() == "650" and b_card.scale_spin.value() == 100
    assert model.row(b.key).weight == 650             # showing it did not write anything back


# ----- advanced ----------------------------------------------------------------------------------
def test_advanced_controls_write_through_and_follow_the_model(page_ab, model, faces):
    a, b, v = faces
    page = page_ab
    assert page.advanced.isHidden() and not page.advanced_button.isChecked()
    page.advanced_button.setChecked(True)
    assert not page.advanced.isHidden()
    assert [page.base_combo.itemText(i) for i in range(page.base_combo.count())] == ["Main", "Fixture A Regular",
                                                                                      "Fixture B Bold"]
    assert page.base_combo.currentIndex() == 0 and model.base_key is None

    page.base_combo.setCurrentIndex(2)
    assert model.base_key == b.key and model.base_index() == 1
    assert page.cards[0].base_badge.isHidden() and not page.cards[1].base_badge.isHidden()
    page.base_combo.setCurrentIndex(0)
    assert model.base_key is None and not page.cards[0].base_badge.isHidden()

    page.default_weight_combo.setCurrentText("600")
    assert (model.default_weight, model.default_scale) == (600, 1.0)
    page.default_scale_spin.setValue(120)
    assert (model.default_weight, model.default_scale) == (600, 1.2)
    page.default_weight_combo.setCurrentText(AS_IS)
    assert model.default_weight is None

    model.set_defaults(500, 0.9)                      # the other way round
    assert page.default_weight_combo.currentText() == "500" and page.default_scale_spin.value() == 90
    model.set_base(a.key)
    assert page.base_combo.currentIndex() == 1
    model.remove(b.key)
    assert page.base_combo.count() == 2 and page.base_combo.currentIndex() == 1


# ----- preview and missing characters ------------------------------------------------------------
def test_sample_text_is_shared_with_the_model_both_ways(page_ab, model):
    page = page_ab
    page.preview.editor.setPlainText("typed here")
    assert model.sample_text == "typed here"
    model.set_sample_text("set there")
    assert page.preview.sample_text() == "set there"


def test_missing_label_lists_what_no_font_covers(page_ab, model):
    page = page_ab
    model.set_sample_text("ab漢 ☺→")
    assert not page.missing_label.isHidden()
    assert page.missing_label.text() == MISSING_PREFIX + "→ ☺" == "Not covered by any font: → ☺"   # code point order
    page.preview.editor.setPlainText("ab漢")          # edited in the preview: the label follows at once
    assert page.missing_label.isHidden() and page.missing_label.text() == ""
    model.set_sample_text("한")
    assert page.missing_label.text() == "Not covered by any font: 한"


def test_refresh_rebuilds_from_the_model(qtbot, model, faces):
    a, b, v = faces
    page = _page(qtbot, model)
    model.blockSignals(True)                          # a change the page did not hear about
    model.add(a)
    model.add(b)
    model.recompute_plan_now()
    model.blockSignals(False)
    assert page.cards == []
    page.refresh()
    assert [c.key for c in page.cards] == [a.key, b.key] and page.placeholder.isHidden()
    assert page.cards[1].plan_label.text() == "supplies Han 1 · CJK symbols & fullwidth 1 (2 characters)"
    assert page.table_groups() == ["latin", "han", "cjk_symbols"]
    assert page.preview.in_plan_mode() and page.preview.current_family() == "Fixture A"


# ----- show all -----------------------------------------------------------------------------------
def test_show_all_button_hides_when_every_script_is_covered(qtbot, model, faces):
    a, b, v = faces
    everything = fake_face(cps(ONE_PER_GROUP), path="all.ttf", family="Fixture All")
    assert everything.scripts == GROUP_IDS                       # one character in each of the 15 groups
    model.add(a)
    page = _page(qtbot, model)
    assert not page.show_all_button.isHidden()                   # Latin only: 14 scripts to reveal
    model.add(everything)
    assert page.show_all_button.isHidden() and page.table.rowCount() == len(GROUPS)
    assert page.supplier_combo("emoji") is not None and page.cell_text("other", COL_COUNTS) == "Fixture All 1"
    model.remove(everything.key)
    assert not page.show_all_button.isHidden() and page.table.rowCount() == 1
    page.show_all_button.click()                                 # checked when every group turns up covered again
    model.add(everything)
    assert page.show_all_button.isHidden() and page.table.rowCount() == len(GROUPS)
    model.remove(everything.key)
    assert not page.show_all_button.isHidden() and page.show_all_button.isChecked()
    assert page.table.rowCount() == len(GROUPS) and page.show_all_button.text() == SHOW_COVERED_TEXT


# ----- adjust title and the variable font sample line -----------------------------------------------
def test_adjust_title_helper():
    assert adjust_title(None, None) == ADJUST_TEXT == "Adjust"
    assert adjust_title(700, None) == "Adjust · boldness 700"
    assert adjust_title(None, 1.1) == "Adjust · size 110 %"
    assert adjust_title(700, 1.1) == "Adjust · boldness 700 · size 110 %"
    assert adjust_title(None, 1.0) == "Adjust"                   # 100 % is the default size


def test_adjust_title_reflects_the_values_set_either_way(page_ab, model, faces):
    a, b, v = faces
    a_card, b_card = page_ab.cards
    assert a_card.adjust_button.text() == "Adjust" and b_card.adjust_button.text() == "Adjust"
    a_card.weight_combo.setCurrentText("700")                    # through the combo
    assert a_card.adjust_button.text() == "Adjust · boldness 700"
    a_card.scale_spin.setValue(110)
    assert a_card.adjust_button.text() == "Adjust · boldness 700 · size 110 %"
    a_card.weight_combo.setCurrentText(AS_IS)
    assert a_card.adjust_button.text() == "Adjust · size 110 %"
    a_card.scale_spin.setValue(100)
    assert a_card.adjust_button.text() == "Adjust"
    model.set_adjust(b.key, 300, 0.8)                            # through the model
    assert b_card.adjust_button.text() == "Adjust · boldness 300 · size 80 %"
    model.set_adjust(b.key, None, None)
    assert b_card.adjust_button.text() == "Adjust"
    assert page_ab.cards[1] is b_card                            # refreshed in place


def test_sample_wght_helper(faces):
    a, b, v = faces
    assert sample_wght(a, None) is None and sample_wght(a, 700) is None   # no weight axis: nothing to draw at
    assert sample_wght(v, None) == 400.0                         # the axis default
    assert sample_wght(v, 700) == 700.0
    assert sample_wght(v, 950) == 900.0 and sample_wght(v, 50) == 100.0   # kept within 100–900


def test_variable_font_sample_line_follows_the_boldness(qtbot, model, faces):
    a, b, v = faces
    model.add(a)
    model.add(v)
    page = _page(qtbot, model)
    a_card, v_card = page.cards
    wght = QFont.Tag("wght")

    def drawn_at(card) -> float | None:
        font = card.sample.document().defaultFont()
        return font.variableAxisValue(wght) if font.isVariableAxisSet(wght) else None

    assert v_card.shown_wght() == 400.0 and drawn_at(v_card) == 400.0
    assert a_card.shown_wght() is None and drawn_at(a_card) is None
    v_card.weight_combo.setCurrentText("700")                    # re-rendered at the chosen boldness
    assert model.row(v.key).weight == 700
    assert v_card.shown_wght() == 700.0 and drawn_at(v_card) == 700.0
    assert "".join(t for t, *_ in _fragments(v_card.sample.document())) == SAMPLE_LINE
    assert "漢" in _red_chars(v_card.sample.document())          # still honest about what it lacks
    model.set_adjust(v.key, None, None)                          # back to the axis default
    assert v_card.shown_wght() == 400.0 and drawn_at(v_card) == 400.0
    model.set_defaults(300, 1.0)                                 # the default boldness applies when it has none
    assert v_card.shown_wght() == 300.0 and drawn_at(v_card) == 300.0
    model.set_adjust(v.key, 900, None)                           # its own boldness wins over the default
    assert v_card.shown_wght() == 900.0 and drawn_at(v_card) == 900.0
    a_card.weight_combo.setCurrentText("700")                    # a static font: nothing to re-render
    assert a_card.shown_wght() is None and drawn_at(a_card) is None
    assert page.cards[1] is v_card and page.cards[0] is a_card


def test_material_card_takes_the_default_weight(faces):
    a, b, v = faces
    card = MaterialCard(MaterialRow(v), 0, 1, True, default_weight=700)
    assert card.shown_wght() == 700.0 and card.adjust_button.text() == "Adjust"   # the default is not "its own"
    card.update_from(MaterialRow(v, weight=200), 0, 1, True, default_weight=700)
    assert card.shown_wght() == 200.0 and card.adjust_button.text() == "Adjust · boldness 200"


# ----- missing characters, glyph warning ------------------------------------------------------------
def test_missing_label_caps_the_list_and_keeps_it_all_in_the_tooltip(page_ab, model):
    page = page_ab
    cyrillic = "".join(chr(cp) for cp in range(0x430, 0x430 + MAX_MISSING_CHARS + 5))   # а б в … 25 letters
    model.set_sample_text("ab " + cyrillic)
    shown = " ".join(cyrillic[:MAX_MISSING_CHARS])
    assert page.missing_label.text() == f"{MISSING_PREFIX}{shown} …"
    assert page.missing_label.toolTip() == " ".join(cyrillic)
    model.set_sample_text("ab " + cyrillic[:MAX_MISSING_CHARS])            # exactly the cap: no ellipsis
    assert page.missing_label.text() == f"{MISSING_PREFIX}{shown}"
    assert page.missing_label.toolTip() == shown
    model.set_sample_text("ab")
    assert page.missing_label.isHidden() and page.missing_label.toolTip() == ""


def test_glyph_warning_shows_as_a_callout_above_the_table(qtbot, page_ab, model, monkeypatch):
    page = page_ab
    assert page.glyph_warning_label.isHidden() and model.glyph_warning() == ""
    monkeypatch.setattr(model, "glyph_warning", lambda: "These fonts come close to the limit.")
    model.recompute_plan_now()                                   # the estimate follows the plan
    assert not page.glyph_warning_label.isHidden()
    assert page.glyph_warning_label.text() == "These fonts come close to the limit."
    assert page.glyph_warning_label.objectName() == "glyphWarning"
    layout = page.table.parentWidget().layout()
    assert layout.indexOf(page.glyph_warning_label) == layout.indexOf(page.table) - 1   # right above the table
    monkeypatch.setattr(model, "glyph_warning", lambda: "")
    page.refresh()
    assert page.glyph_warning_label.isHidden() and page.glyph_warning_label.text() == ""
    monkeypatch.delattr(model, "glyph_warning")
    monkeypatch.delattr(ForgeModel, "glyph_warning")             # an older model without the API: no callout
    page.refresh()
    assert page.glyph_warning_label.isHidden()


# ----- lock ----------------------------------------------------------------------------------------
def _card_controls(card):
    return [card.up_button, card.down_button, card.weight_combo, card.scale_spin]


def test_locked_page_disables_the_controls_but_keeps_the_previews_live(qtbot, page_ab, model, faces):
    a, b, v = faces
    page = page_ab
    a_card, b_card = page.cards
    assert not page.is_locked() and not a_card.is_locked()
    page.set_locked(True)
    assert page.is_locked() and a_card.is_locked() and b_card.is_locked()
    for card in page.cards:
        assert not any(w.isEnabled() for w in _card_controls(card))
    assert not page.supplier_combo("latin").isEnabled() and not page.supplier_combo("han").isEnabled()
    assert not page.base_combo.isEnabled() and not page.default_weight_combo.isEnabled()
    assert not page.default_scale_spin.isEnabled()
    assert a_card.adjust_button.isEnabled() and page.advanced_button.isEnabled()   # looking is still allowed
    a_card.down_button.click()
    assert model.keys() == [a.key, b.key]                        # disabled: nothing moved
    # the previews stay live: the sample text and the missing line keep following the model
    model.set_sample_text("ab 한")
    assert page.preview.sample_text() == "ab 한" and page.missing_label.text() == "Not covered by any font: 한"
    # changes made elsewhere (a settings file, the tray) still reach the cards and the table, locked
    model.set_adjust(b.key, 300, None)
    assert b_card.weight_combo.currentText() == "300" and not b_card.weight_combo.isEnabled()
    assert b_card.adjust_button.text() == "Adjust · boldness 300"
    model.add(v)                                                 # rebuilt cards and table come out locked
    assert [c.key for c in page.cards] == [a.key, b.key, v.key]
    for card in page.cards:
        assert card.is_locked() and not any(w.isEnabled() for w in _card_controls(card))
    for g in page.table_groups():
        assert not page.supplier_combo(g).isEnabled()
    page.set_locked(False)
    assert not page.is_locked()
    first, second, third = page.cards
    assert not first.up_button.isEnabled() and first.down_button.isEnabled()
    assert second.up_button.isEnabled() and second.down_button.isEnabled()
    assert third.up_button.isEnabled() and not third.down_button.isEnabled()
    for card in page.cards:
        assert card.weight_combo.isEnabled() and card.scale_spin.isEnabled()
    for g in page.table_groups():
        assert page.supplier_combo(g).isEnabled()
    assert page.base_combo.isEnabled() and page.default_weight_combo.isEnabled() and page.default_scale_spin.isEnabled()
    third.up_button.click()
    assert model.keys() == [a.key, v.key, b.key]
    page.set_locked(False)                                       # already unlocked: harmless
    assert page.cards[0].down_button.isEnabled()


def test_lock_with_no_fonts_keeps_the_base_combo_off(qtbot, model):
    page = _page(qtbot, model)
    page.set_locked(True)
    page.set_locked(False)
    assert not page.base_combo.isEnabled()                       # no rows: nothing to choose from
    assert page.default_weight_combo.isEnabled() and page.default_scale_spin.isEnabled()


def test_apply_theme_recolours_cards_table_and_sheet(qtbot, page_ab, model):
    page = page_ab
    card = page.cards[0]                       # A lacks 漢 and more: its sample has red characters
    assert _red_chars(card.sample.document()) and LIGHT.surface in page.styleSheet()
    page.apply_theme(DARK)
    # LIGHT.surface is no sentinel here: DARK.on_accent is the same white and the Main badge uses it
    assert DARK.surface in page.styleSheet() and LIGHT.accent not in page.styleSheet()
    assert _red_chars(card.sample.document(), DARK.missing) and not _red_chars(card.sample.document())
    page.show_all_button.setChecked(True)      # uncovered rows are the muted ones
    row = page.table_row("arabic")
    assert page.table.item(row, 1).foreground().color().name() == DARK.muted
    model.add(model.catalog[next(k for k in model.catalog if k not in model.keys())])
    assert page.cards[-1]._theme is DARK       # cards built after the switch get the current theme
