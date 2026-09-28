from dataclasses import replace
from pathlib import Path

import pytest

from fontplayground.engine.merge import MAX_GLYPHS
from fontplayground.engine.scripts import GROUP_IDS, group_of
from fontplayground.engine.spec import MaterialSpec, Plan
from fontplayground.ui import smart
from fontplayground.ui.smart import (GLYPH_WARN, default_face, default_family_name, default_output_path, default_style,
                                     estimate_glyphs, exceeds_glyph_budget, face_glyph_share, group_counts,
                                     resolve_rules, smart_supplier, strip_vendor, suggest_materials)
from tests.fixtures import cps, fake_face

LATIN = set(range(0x20, 0x250))            # 560 code points, all in the "latin" group
HAN = set(range(0x4E00, 0x4E00 + 3000))    # 3000 code points of Han
HANGUL = set(range(0xAC00, 0xAC00 + 100))
# 1,605 code points of the "symbols" group (arrows, maths, box drawing, dingbats…): punctuation & symbols
SYMBOLS = [cp for cp in range(0x2190, 0x2800) if group_of(cp) == "symbols"]
# 28,000 Han code points: the URO block, Extension A and the start of Extension B
HAN_28000 = set(range(0x4E00, 0x4E00 + 20992)) | set(range(0x3400, 0x3400 + 6592)) | set(range(0x20000, 0x20000 + 416))


@pytest.fixture
def segoe():
    """A Latin-heavy main font with a token Han range (like Segoe UI)."""
    return fake_face(LATIN | set(range(0x4E00, 0x4E00 + 30)), path="segoe.ttf", family="Segoe UI")


@pytest.fixture
def yahei():
    """A Han-heavy font with a smaller Latin range (like Microsoft YaHei): 200 Latin < 560 / 2."""
    return fake_face(HAN | set(range(0x41, 0x41 + 200)), path="yahei.ttc", index=1, family="Microsoft YaHei")


# ----- group counts ------------------------------------------------------------------------------
def test_group_counts_counts_every_group_per_face(segoe, yahei):
    counts = group_counts([segoe, yahei])
    assert set(counts) == {segoe.key, yahei.key}
    assert set(counts[segoe.key]) == set(GROUP_IDS)
    assert counts[segoe.key]["latin"] == 560 and counts[segoe.key]["han"] == 30
    assert counts[yahei.key]["han"] == 3000 and counts[yahei.key]["latin"] == 200
    assert counts[yahei.key]["hangul"] == 0


def test_group_counts_come_from_the_face_and_callers_get_copies(segoe):
    counts = group_counts([segoe])[segoe.key]
    assert counts == segoe.counts
    counts["latin"] = 0
    assert group_counts([segoe])[segoe.key]["latin"] == 560


def test_default_face_matches_main_italic_then_weight():
    regular = fake_face(cps("a"), path="f.ttc", index=0, family="F", style="Regular")
    bold = fake_face(cps("a"), path="f.ttc", index=1, family="F", style="Bold", weight=700)
    italic = replace(fake_face(cps("a"), path="f.ttc", index=2, family="F", style="Italic"), italic=True)
    broken = fake_face(cps("a"), path="f.ttc", index=3, family="F", style="Black", weight=900, outline="none")
    faces = [bold, italic, regular, broken]
    assert default_face(faces, None) == regular                      # no main: upright, 400
    assert default_face(faces, bold) == bold
    assert default_face(faces, replace(bold, italic=True)) == italic
    assert default_face([broken], None) == broken                    # nothing supported: still inspectable
    assert default_face([], None) is None
    black_main = fake_face(cps("a"), path="m.ttf", weight=900)
    assert default_face(faces, black_main) == bold                    # the unsupported Black is skipped


# ----- suppliers ---------------------------------------------------------------------------------
def test_han_goes_to_yahei_and_latin_stays_with_segoe_when_segoe_is_main(segoe, yahei):
    counts = group_counts([segoe, yahei])
    assert smart_supplier("han", counts, [segoe.key, yahei.key]) == yahei.key    # 30 Han < 3000 / 10: Main lets go
    assert smart_supplier("latin", counts, [segoe.key, yahei.key]) == segoe.key
    assert smart_supplier("han", counts, [yahei.key, segoe.key]) == yahei.key
    assert smart_supplier("latin", counts, [yahei.key, segoe.key]) == yahei.key  # as Main, 200 Latin >= 560 / 10: kept


def test_a_material_below_main_needs_half_the_best_count(segoe, yahei):
    hangul = fake_face(HANGUL, path="hangul.ttf", family="Hangul Only")  # a Main that covers no Latin at all
    counts = group_counts([hangul, segoe, yahei])
    counts[yahei.key]["latin"] = 280  # exactly half of Segoe's 560
    assert smart_supplier("latin", counts, [hangul.key, yahei.key, segoe.key]) == yahei.key
    counts[yahei.key]["latin"] = 279
    assert smart_supplier("latin", counts, [hangul.key, yahei.key, segoe.key]) == segoe.key
    assert smart_supplier("latin", counts, [hangul.key, segoe.key, yahei.key]) == segoe.key


def test_main_keeps_a_group_it_covers_a_tenth_as_well_as_the_best_material():
    georgia = fake_face(LATIN | set(SYMBOLS[:120]), path="georgia.ttf", family="Georgia")   # 120 punctuation & symbols
    cjk = fake_face(HAN_28000 | set(SYMBOLS[:1200]), path="cjk.ttf", family="CJK")          # 1,200 of them, 28,000 Han
    counts = group_counts([georgia, cjk])
    assert counts[georgia.key]["symbols"] == 120 and counts[georgia.key]["han"] == 0
    assert counts[cjk.key]["symbols"] == 1200 and counts[cjk.key]["han"] == 28000
    order = [georgia.key, cjk.key]
    assert smart_supplier("symbols", counts, order) == georgia.key   # Main: 120 >= 1200 / 10
    assert smart_supplier("latin", counts, order) == georgia.key
    assert smart_supplier("han", counts, order) == cjk.key           # Georgia has no Han at all
    counts[georgia.key]["han"] = 2
    assert smart_supplier("han", counts, order) == cjk.key           # a token Han range: 2 < 28000 / 10
    counts[cjk.key]["symbols"] = 1201
    assert smart_supplier("symbols", counts, order) == cjk.key       # just under a tenth: the CJK font takes over
    counts[cjk.key]["symbols"] = 1200
    third = ("third.ttf", 0)                                          # only the first key gets the Main bias
    assert smart_supplier("symbols", counts, [third, georgia.key, cjk.key]) == cjk.key
    assert smart_supplier("symbols", counts, [cjk.key, georgia.key]) == cjk.key


def test_supplier_is_none_when_nobody_covers_the_group(segoe, yahei):
    counts = group_counts([segoe, yahei])
    assert smart_supplier("hangul", counts, [segoe.key, yahei.key]) is None
    assert smart_supplier("hangul", counts, []) is None
    assert smart_supplier("latin", {}, [segoe.key]) is None  # unknown keys count as 0


def test_resolve_rules_uses_pins_when_present_and_smart_otherwise(segoe, yahei):
    counts = group_counts([segoe, yahei])
    order = [segoe.key, yahei.key]
    rules = resolve_rules(order, {}, counts)
    assert set(rules) == set(GROUP_IDS)
    assert rules["latin"] == 0 and rules["han"] == 1 and rules["hangul"] is None
    pinned = resolve_rules(order, {"han": segoe.key, "hangul": yahei.key}, counts)
    assert pinned["han"] == 0           # the pin wins even though Segoe has only 30 Han characters
    assert pinned["hangul"] == 1        # a pin to a font that covers nothing is still honoured
    gone = resolve_rules(order, {"han": ("missing.ttf", 0), "latin": None}, counts)
    assert gone["han"] == 1 and gone["latin"] == 0


# ----- names -------------------------------------------------------------------------------------
@pytest.mark.parametrize("family, expected", [
    ("Microsoft YaHei", "YaHei"),
    ("MS Gothic", "Gothic"),
    ("Adobe Song Std", "Song Std"),
    ("Google Sans", "Sans"),
    ("microsoft ms Mincho", "Mincho"),
    ("Segoe UI", "Segoe UI"),
    ("Microsoft", "Microsoft"),
    ("  Noto  Sans  ", "Noto Sans"),
])
def test_strip_vendor(family, expected):
    assert strip_vendor(family) == expected


def test_default_family_name_pairs_main_and_second_with_vendors_stripped(segoe, yahei):
    assert default_family_name([segoe, yahei]) == "Segoe UI YaHei"
    assert default_family_name([yahei, segoe]) == "YaHei Segoe UI"


def test_default_family_name_falls_back_to_forged():
    assert default_family_name([]) == "Forged"
    single = fake_face(cps("a"), family="Microsoft JhengHei")
    assert default_family_name([single]) == "JhengHei Forged"
    long_a = fake_face(cps("a"), path="a.ttf", family="Source Han Sans HW SC")
    long_b = fake_face(cps("b"), path="b.ttf", family="Bahnschrift SemiCondensed")
    assert len(f"{long_a.family} {long_b.family}") > 31
    assert default_family_name([long_a, long_b]) == "Source Han Sans HW SC Forged"
    regular = fake_face(cps("a"), path="r.ttf", family="Noto Sans", style="Regular")
    bold = fake_face(cps("a"), path="b.ttf", family="Noto Sans", style="Bold")
    assert default_family_name([regular, bold]) == "Noto Sans Forged"  # two faces of one family are not a pair
    third = fake_face(cps("a"), path="c.ttf", family="Noto Serif")
    assert default_family_name([regular, bold, third]) == "Noto Sans Noto Serif"


def test_default_style_follows_main():
    assert default_style(fake_face(cps("a"), style="Semibold Italic")) == "Semibold Italic"
    assert default_style(fake_face(cps("a"), style="  ")) == "Regular"
    assert default_style(None) == "Regular"


def test_default_output_path_lives_in_documents_and_is_a_safe_file_name():
    assert default_output_path("Segoe UI YaHei", "Regular") == Path.home() / "Documents" / "Segoe UI YaHei-Regular.ttf"
    assert default_output_path('A/B:C?', "Bold").name == "A-B-C--Bold.ttf"
    assert default_output_path("  ", "").name == "Forged-Regular.ttf"


# ----- suggestions -------------------------------------------------------------------------------
def _catalog():
    return [
        fake_face(cps("abc"), path="latin.ttf", family="Latin Only"),
        fake_face(HAN | cps("a"), path="han.ttf", family="Han Font"),
        fake_face(HANGUL | HAN, path="kr-bold.ttf", family="Korean", style="Bold", weight=700),
        fake_face(HANGUL | HAN, path="kr.ttf", family="Korean", style="Regular", weight=400),
        fake_face(HANGUL, path="kr-light.ttf", family="Korean", style="Light", weight=300),
        fake_face(cps("☺→"), path="sym.ttf", family="Symbols"),
        fake_face(HANGUL | HAN | cps("☺→"), path="color.ttf", family="Colour Everything", has_color=True),
    ]


def test_suggest_materials_ranks_families_by_coverage_one_face_per_family():
    missing = HANGUL | {0x4E00, 0x4E01} | cps("☺")
    main = fake_face(cps("a"), path="main.ttf", family="Main", weight=400)
    got = suggest_materials(missing, _catalog(), main)
    assert [f.family for f in got] == ["Korean", "Han Font", "Symbols"]  # covers 102, 2 and 1 of them
    assert got[0].style == "Regular"                     # closest weight to Main's 400
    assert "Colour Everything" not in {f.family for f in got}  # unsupported faces are never suggested


def test_suggest_materials_prefers_main_italic_and_weight():
    catalog = _catalog()
    italic = replace(catalog[3], italic=True, style="Italic", path="kr-italic.ttf")
    main = fake_face(cps("a"), path="main.ttf", family="Main", weight=700)
    got = suggest_materials(HANGUL, catalog + [italic], main, limit=1)
    assert got == [catalog[2]]  # Korean Bold: matches the weight, italic flag matches too
    main_italic = replace(main, italic=True)
    got = suggest_materials(HANGUL, catalog + [italic], main_italic, limit=1)
    assert got == [italic]      # the italic flag wins over the closer weight
    got = suggest_materials(HANGUL, catalog, None, limit=1)
    assert got == [catalog[3]]  # no Main: upright, weight 400


def test_suggest_materials_limit_exclusions_and_empty_cases():
    catalog = _catalog()
    missing = HANGUL | cps("☺")
    assert suggest_materials(missing, catalog, None, limit=1) == [catalog[3]]
    assert suggest_materials(missing, catalog, None, limit=0) == []
    assert suggest_materials(set(), catalog, None) == []
    without_korean = suggest_materials(missing, catalog, None, exclude_keys=[c.key for c in catalog if c.family == "Korean"])
    assert [f.family for f in without_korean] == ["Symbols"]
    assert suggest_materials(cps("z"), catalog, None) == []  # nobody covers it


def test_suggest_materials_keeps_catalog_order_on_ties():
    first = fake_face(cps("x"), path="first.ttf", family="First")
    second = fake_face(cps("x"), path="second.ttf", family="Second")
    assert [f.family for f in suggest_materials(cps("x"), [first, second], None)] == ["First", "Second"]
    assert [f.family for f in suggest_materials(cps("x"), [second, first], None)] == ["Second", "First"]


def test_suggest_materials_prefers_fewer_glyphs_on_equal_coverage():
    lean = replace(fake_face(cps("x"), path="lean.ttf", family="Lean"), glyph_count=50)
    heavy = replace(fake_face(cps("x"), path="heavy.ttf", family="Heavy"), glyph_count=500)
    assert [f.family for f in suggest_materials(cps("x"), [heavy, lean], None)] == ["Lean", "Heavy"]
    assert [f.family for f in suggest_materials(cps("x"), [lean, heavy], None)] == ["Lean", "Heavy"]
    bigger = fake_face(cps("xy"), path="bigger.ttf", family="Bigger")  # coverage still comes first
    assert [f.family for f in suggest_materials(cps("xy"), [heavy, lean, bigger], None)] == ["Bigger", "Lean", "Heavy"]


def test_suggest_materials_demotes_faces_that_would_pass_the_glyph_limit():
    catalog = _catalog()
    huge = replace(fake_face(HANGUL | HAN, path="huge.ttf", family="Huge"), glyph_count=60_000)
    missing = HANGUL | {0x4E00, 0x4E01} | cps("☺")
    families = lambda faces: [f.family for f in faces]  # noqa: E731
    # Huge and Korean both cover 102 characters: the smaller face (Korean Regular, 101 glyphs) ranks first
    got = suggest_materials(missing, catalog + [huge], None, limit=4)
    assert families(got) == ["Korean", "Huge", "Han Font", "Symbols"]
    # 60,000 × 0.8 + 17,535 = 65,535 is still allowed; one glyph more and Huge goes to the end
    assert not exceeds_glyph_budget(huge, MAX_GLYPHS - 48_000) and exceeds_glyph_budget(huge, MAX_GLYPHS - 48_000 + 1)
    assert families(suggest_materials(missing, catalog + [huge], None, limit=4, main_glyphs=17_535))[1] == "Huge"
    assert families(suggest_materials(missing, catalog + [huge], None, limit=4, main_glyphs=20_000)) == [
        "Korean", "Han Font", "Symbols", "Huge"]
    got = suggest_materials(missing, catalog + [huge], None, main_glyphs=20_000)
    assert families(got) == ["Korean", "Han Font", "Symbols"]  # limit 3: the demoted face falls off the list
    assert families(suggest_materials(HAN, [huge], None, main_glyphs=20_000)) == ["Huge"]  # demoted, not hidden


# ----- glyph budget ------------------------------------------------------------------------------
def test_glyph_share_scales_a_face_by_its_planned_characters_and_the_variant_factor():
    face = replace(fake_face(set(range(100)), path="big.ttf"), glyph_count=1000)
    assert face_glyph_share(face, 100) == 800 and face_glyph_share(face, 50) == 400 and face_glyph_share(face, 0) == 0
    small = fake_face(cps("abc"), path="small.ttf")                        # 4 glyphs for 3 characters
    assert face_glyph_share(small, 1) == 1                                 # round(4 / 3 × 0.8)
    empty = replace(fake_face(set(), path="empty.ttf"), glyph_count=7)     # no character map: no division by zero
    assert face_glyph_share(empty, 0) == 0


def test_estimate_glyphs_adds_notdef_and_every_material_share():
    big = replace(fake_face(set(range(100)), path="big.ttf"), glyph_count=1000)
    small = fake_face(cps("abc"), path="small.ttf")
    empty = replace(fake_face(set(), path="empty.ttf"), glyph_count=7)
    plan = Plan({0: set(range(50)), 1: cps("a"), 2: set()}, {})
    assert estimate_glyphs([MaterialSpec(big), MaterialSpec(small), MaterialSpec(empty)], plan) == 1 + 400 + 1 + 0
    assert estimate_glyphs([big, small, empty], plan) == 402                       # bare faces work too
    assert estimate_glyphs([big, small], Plan({0: set(range(100))}, {})) == 801   # no plan entry: nothing planned
    assert estimate_glyphs([], Plan({}, {})) == 1
    assert GLYPH_WARN == 58_000 and GLYPH_WARN < MAX_GLYPHS == 65_535
