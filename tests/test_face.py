from fontplayground.catalog.face import read_faces
from tests.fixtures import fake_face


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
