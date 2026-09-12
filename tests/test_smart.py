from dataclasses import replace
from pathlib import Path

import pytest

from fontplayground.engine.scripts import GROUP_IDS
from fontplayground.ui import smart
from fontplayground.ui.smart import (default_family_name, default_output_path, default_style, group_counts,
                                     resolve_rules, smart_supplier, strip_vendor, suggest_materials)
from tests.fixtures import cps, fake_face

LATIN = set(range(0x20, 0x250))            # 560 code points, all in the "latin" group
HAN = set(range(0x4E00, 0x4E00 + 3000))    # 3000 code points of Han
HANGUL = set(range(0xAC00, 0xAC00 + 100))


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


def test_group_counts_are_cached_per_face_key_and_size(segoe):
    smart._counts.cache_clear()
    group_counts([segoe])
    rescanned = replace(segoe, mtime=2.0)  # a rescan yields a new object for the same file
    group_counts([rescanned])
    assert smart._counts.cache_info().hits == 1
    grown = replace(segoe, codepoints=frozenset(segoe.codepoints | HANGUL))
    assert group_counts([grown])[grown.key]["hangul"] == 100  # a changed font misses the cache
    assert smart._counts.cache_info().misses == 2
    group_counts([segoe])[segoe.key]["latin"] = 0
    assert group_counts([segoe])[segoe.key]["latin"] == 560  # callers get copies


# ----- suppliers ---------------------------------------------------------------------------------
def test_han_goes_to_yahei_and_latin_stays_with_segoe_in_both_orders(segoe, yahei):
    counts = group_counts([segoe, yahei])
    for order in ([segoe.key, yahei.key], [yahei.key, segoe.key]):
        assert smart_supplier("han", counts, order) == yahei.key
        assert smart_supplier("latin", counts, order) == segoe.key


def test_supplier_is_the_first_material_with_at_least_half_the_best_count(segoe, yahei):
    counts = group_counts([segoe, yahei])
    counts[yahei.key]["latin"] = 280  # exactly half of Segoe's 560
    assert smart_supplier("latin", counts, [yahei.key, segoe.key]) == yahei.key
    assert smart_supplier("latin", counts, [segoe.key, yahei.key]) == segoe.key


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
