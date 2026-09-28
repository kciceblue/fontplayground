import pytest

from fontplayground.catalog.face import read_faces
from fontplayground.engine.scripts import GROUP_IDS
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


def test_local_names_come_from_non_english_windows_records(tmp_path):
    path = build_font(tmp_path / "L.ttf", "Fixture L", "Regular", cps("a漢"), name_records={
        1: [(3, 1, 0x409, "Fixture L"), (3, 1, 0x411, "テスト"), (3, 1, 0x804, "测试字体"), (3, 1, 0x404, "fixture l")],
        16: [(3, 1, 0x409, "Fixture L"), (3, 1, 0x804, "测试")]})
    face = read_faces(path)[0]
    assert face.family == "Fixture L"
    # zh-CN's typographic family beats its name ID 1; Japanese next; the one equal to the family is dropped
    assert face.local_names == ("测试", "テスト")


def test_local_names_fall_back_to_mac_japanese_records_and_are_empty_for_plain_fonts(tmp_path, font_dir):
    path = build_font(tmp_path / "M.ttf", "Fixture M", "Regular", cps("a"), name_records={
        1: [(3, 1, 0x409, "Fixture M"), (1, 1, 11, JA)]})
    assert read_faces(path)[0].local_names == (JA,)
    assert read_faces(font_dir / "A.ttf")[0].local_names == ()


def test_group_counts_are_read_with_the_face(font_dir):
    (b,) = read_faces(font_dir / "B.otf")                    # cps("ab漢，")
    assert b.group_counts == (("latin", 2), ("han", 1), ("cjk_symbols", 1))
    assert b.counts["han"] == 1 and b.counts["hangul"] == 0 and set(b.counts) == set(GROUP_IDS)


def test_counts_fall_back_to_the_codepoints():
    face = fake_face(cps("ab漢"))
    assert face.group_counts == ()
    assert face.counts["latin"] == 2 and face.counts["han"] == 1 and face.scripts == ["latin", "han"]
