from fontTools.ttLib import TTFont

from fontplayground.catalog.face import read_faces
from fontplayground.engine.prepare import prepare
from fontplayground.engine.spec import MaterialSpec
from fontplayground.engine.synth_bold import embolden, stroke_width
from tests.fixtures import cps


def test_stroke_width():
    assert stroke_width(300, 1000) == 60 and stroke_width(300, 2048) == 2048 * 0.06


def test_embolden_widens_glyph_and_advance(font_dir):
    f = TTFont(str(font_dir / "A.ttf"))
    embolden(f, 300)
    g = f["glyf"]["uni0061"]; g.recalcBounds(f["glyf"])
    assert g.xMin == 50 and abs(g.xMax - 210) <= 1          # stem 100 -> 160, shifted so lsb stays 50
    assert f["hmtx"]["uni0061"] == (260, 50)
    assert f["hhea"].advanceWidthMax == 260


def test_prepare_applies_synthetic_bold_only_when_needed(font_dir, tmp_path):
    (a,) = read_faces(font_dir / "A.ttf")
    pf = prepare(MaterialSpec(a), cps("a"), 1000, 700, 1.0, tmp_path, 0)
    assert pf.warnings == ["synthetic bold (+300)"] and TTFont(pf.path)["hmtx"]["uni0061"][0] == 260
    light = prepare(MaterialSpec(a), cps("a"), 1000, 100, 1.0, tmp_path, 1)
    assert light.warnings == ["cannot make lighter than source; weight left as is"]
    same = prepare(MaterialSpec(a), cps("a"), 1000, 420, 1.0, tmp_path, 2)
    assert same.warnings == []
    (v,) = read_faces(font_dir / "V.ttf")
    assert prepare(MaterialSpec(v), cps("a"), 1000, 900, 1.0, tmp_path, 3).warnings == []


def test_composite_glyph_is_emboldened_once(font_dir):
    f = TTFont(str(font_dir / "K.ttf"))
    embolden(f, 300)
    base, comp = f["glyf"]["uni0061"], f["glyf"]["uni00E0"]
    base.recalcBounds(f["glyf"])
    comp.recalcBounds(f["glyf"])
    assert (comp.xMin, comp.xMax) == (base.xMin, base.xMax)
    assert f["hmtx"]["uni00E0"] == f["hmtx"]["uni0061"] == (260, 50)
    assert comp.numberOfContours >= 1  # decomposed into a simple glyph
