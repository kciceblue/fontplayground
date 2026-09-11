from fontTools.ttLib import TTCollection, TTFont


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
