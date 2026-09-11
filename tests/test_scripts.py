import pytest

from fontplayground.engine.scripts import GROUP_IDS, GROUPS, LABELS, group_of, groups_covered


@pytest.mark.parametrize("char,group", [
    ("a", "latin"), ("1", "latin"), (",", "latin"), ("\u00e9", "latin"),
    ("\u03a9", "greek"), ("\u0434", "cyrillic"), ("\u0628", "arabic"), ("\u05d0", "hebrew"),
    ("\u0928", "indic"), ("\u0e01", "southeast_asian"), ("\ud55c", "hangul"), ("\u3042", "kana"),
    ("\u6f22", "han"), ("\uff0c", "cjk_symbols"), ("\u3001", "cjk_symbols"),
    ("\u2192", "symbols"), ("\u263a", "symbols"), ("\u20ac", "symbols"),
    ("\U0001f600", "emoji"), ("\u1200", "other"),
])
def test_group_of(char, group):
    assert group_of(ord(char)) == group


def test_groups_are_ordered_and_labelled():
    assert GROUP_IDS[0] == "latin" and GROUP_IDS[-1] == "other"
    assert len(GROUPS) == 15 and all(g.id in LABELS for g in GROUPS)


def test_groups_covered_in_group_order():
    assert groups_covered({0x6F22, ord("a"), 0xFF0C}) == ["latin", "han", "cjk_symbols"]
