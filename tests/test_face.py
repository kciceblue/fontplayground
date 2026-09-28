import pytest

from fontplayground.catalog.face import read_faces
from tests.fixtures import build_font, cps, fake_face

JA = "テスト明朝"
SJIS_AS_MAC_ROMAN = (1, 0, 0, JA.encode("shift_jis"))  # how EPSON's Japanese fonts store it; decodes as mojibake


def test_read_glyf_face(font_dir):
    (f,) = read_faces(font_dir / "A.ttf")
    assert (f.family, f.style, f.outline, f.upem, f.weight_class) == ("Fixture A", "Regular", "glyf", 1000, 400)
    assert f.codepoints == frozenset({44, 49, 97, 98, 99}) and f.glyph_count == 6
    assert f.supported and f.format_tag == "TTF" and f.embedding == "installable"
    assert f.scripts == ["latin"] and f.key == (str(font_dir / "A.ttf"), 0)


def test_read_cff_and_restricted(font_dir):
    (b,) = read_faces(font_dir / "B.otf")
    assert b.outline == "CFF" and b.format_tag == "OTF" and b.weight_class == 700
    assert b.scripts == ["latin", "han", "cjk_symbols"]
    (c,) = read_faces(font_dir / "C.ttf")
    assert c.embedding == "restricted"


def test_read_variable(font_dir):
    (v,) = read_faces(font_dir / "V.ttf")
    assert v.is_variable and v.axes == (("wght", 100.0, 400.0, 900.0),) and v.format_tag == "VAR"
    assert v.has_wght_axis


def test_read_collection(font_dir):
    faces = read_faces(font_dir / "T.ttc")
    assert [(f.family, f.index, f.is_collection) for f in faces] == [("Fixture A", 0, True), ("Fixture C", 1, True)]
    assert faces[0].format_tag == "TTC"


def test_unsupported_reasons():
    assert fake_face({97}, outline="none").unsupported_reason == "bitmap-only font (no outlines)"
    assert fake_face({97}, outline="CFF2").unsupported_reason == "CFF2 outlines are not supported"
    assert fake_face({97}, has_color=True).unsupported_reason == "colour fonts are not supported"
    assert fake_face({97}).unsupported_reason is None


@pytest.mark.parametrize("records, family", [
    ([(1, 1, 11, JA)], JA),                                   # only a Mac Japanese record: decoded as Shift-JIS
    ([SJIS_AS_MAC_ROMAN, (1, 1, 11, JA)], JA),                # ...and preferred to a Mac Roman one
    ([SJIS_AS_MAC_ROMAN, (3, 1, 0x411, JA)], JA),             # a Windows record of any language beats Mac ones
    ([(1, 1, 11, JA), (3, 1, 0x411, JA), (3, 1, 0x409, "Test Mincho")], "Test Mincho"),  # Windows English first
    ([(1, 0, 0, "Old Mac")], "Old Mac"),                      # nothing better: Mac Roman is still read
    ([], "Stem"),                                             # no family record: the file name
])
def test_family_comes_from_a_correctly_decoded_record(tmp_path, records, family):
    path = build_font(tmp_path / "Stem.ttf", "Unused", "Regular", cps("ab"), name_records={1: records})
    assert read_faces(path)[0].family == family


def test_style_comes_from_a_correctly_decoded_record(tmp_path):
    records = [(1, 0, 0, "標準".encode("shift_jis")), (3, 1, 0x411, "標準")]
    path = build_font(tmp_path / "S.ttf", "Fixture S", "Unused", cps("ab"), name_records={2: records})
    assert read_faces(path)[0].style == "標準"
