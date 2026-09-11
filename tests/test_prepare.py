from fontTools.ttLib import TTFont

from fontplayground.catalog.face import read_faces
from fontplayground.engine.prepare import KEEP_TABLES, prepare
from fontplayground.engine.spec import MaterialSpec
from tests.fixtures import cps


def _prep(font_dir, name, codepoints, tmp_path, **kw):
    (face,) = read_faces(font_dir / name)
    kw.setdefault("weight", None); kw.setdefault("scale", 1.0); kw.setdefault("target_upem", 1000)
    pf = prepare(MaterialSpec(face), codepoints, workdir=tmp_path, index=0, **kw)
    return pf, TTFont(pf.path)


def test_subset_keeps_only_assigned(font_dir, tmp_path):
    pf, f = _prep(font_dir, "A.ttf", cps("ab"), tmp_path)
    assert set(f.getBestCmap()) == cps("ab") and pf.warnings == []
    assert set(f.keys()) - {"GlyphOrder"} <= KEEP_TABLES


def test_cff_becomes_glyf(font_dir, tmp_path):
    _, f = _prep(font_dir, "B.otf", cps("a漢"), tmp_path)
    assert "glyf" in f and "CFF " not in f and f.sfntVersion == "\x00\x01\x00\x00"
    g = f["glyf"]["uni0061"]; g.recalcBounds(f["glyf"])
    assert (g.xMin, g.xMax) == (50, 150)


def test_scale_and_upem_normalisation(font_dir, tmp_path):
    _, f = _prep(font_dir, "C.ttf", cps("a"), tmp_path)           # 2048 -> 1000
    assert f["head"].unitsPerEm == 1000 and f["hmtx"]["uni0061"][0] == 200
    _, h = _prep(font_dir, "A.ttf", cps("a"), tmp_path, scale=0.5)
    assert h["head"].unitsPerEm == 1000 and h["hmtx"]["uni0061"][0] == 100


def test_variable_instanced_at_weight(font_dir, tmp_path):
    _, f = _prep(font_dir, "V.ttf", cps("a"), tmp_path, weight=900)
    assert "fvar" not in f and f["hmtx"]["uni0061"][0] == 300
    _, d = _prep(font_dir, "V.ttf", cps("a"), tmp_path, weight=None)
    assert d["hmtx"]["uni0061"][0] == 200


def test_empty_assignment_gives_notdef_only(font_dir, tmp_path):
    _, f = _prep(font_dir, "A.ttf", set(), tmp_path)
    assert f.getGlyphOrder() == [".notdef"]
