from fontTools.ttLib import TTCollection, TTFont

from tests.fixtures import build_font, cps


def test_fixture_fonts(font_dir):
    a = TTFont(str(font_dir / "A.ttf"))
    assert sorted(a.getBestCmap()) == [44, 49, 97, 98, 99] and "glyf" in a
    b = TTFont(str(font_dir / "B.otf"))
    assert "CFF " in b and 0x6F22 in b.getBestCmap()
    c = TTFont(str(font_dir / "C.ttf"))
    assert c["head"].unitsPerEm == 2048 and c["hmtx"]["uni0061"][0] == 409
    v = TTFont(str(font_dir / "V.ttf"))
    assert "fvar" in v and "gvar" in v
    assert len(TTCollection(str(font_dir / "T.ttc")).fonts) == 2


def test_name_records_replace_every_record_of_a_name_id(tmp_path):
    p = build_font(tmp_path / "J.ttf", "Unused", "Regular", cps("ab"), name_records={1: [(1, 1, 11, "テスト明朝")]})
    names = TTFont(str(p))["name"].names
    family = [(r.platformID, r.platEncID, r.langID, r.string) for r in names if r.nameID == 1]
    assert family == [(1, 1, 11, "テスト明朝".encode("shift_jis"))]  # only a Mac Japanese record, in Shift-JIS
