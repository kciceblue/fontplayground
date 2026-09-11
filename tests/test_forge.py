import pytest
from fontTools.ttLib import TTFont

from fontplayground.catalog.face import read_faces
from fontplayground.engine.forge import forge
from fontplayground.engine.spec import ForgeError, ForgeSpec, MaterialSpec
from tests.fixtures import cps


def faces(font_dir, *names):
    return [read_faces(font_dir / n)[0] for n in names]


def test_forge_two_materials_end_to_end(font_dir, tmp_path):
    a, b = faces(font_dir, "A.ttf", "B.otf")
    spec = ForgeSpec(materials=[MaterialSpec(a), MaterialSpec(b)], script_rules={"han": 1},
                     family_name="Forged Test", style_name="Regular")
    stages = []
    out = tmp_path / "out" / "forged.ttf"
    report = forge(spec, out, progress=lambda s, f: stages.append(s))
    f = TTFont(str(out))
    cmap = f.getBestCmap()
    assert set(cmap) == cps("abc1,漢，") and report.total_codepoints == 7
    assert f["maxp"].numGlyphs == 8 == report.total_glyphs  # 7 glyphs + one .notdef
    assert f["name"].getBestFamilyName() == "Forged Test" and f["name"].getDebugName(6) == "ForgedTest-Regular"
    assert f["head"].unitsPerEm == 1000 and (f["hhea"].ascent, f["hhea"].descent) == (800, -200)
    assert f["OS/2"].fsType == 0 and f["OS/2"].usWeightClass == 400
    assert cmap[0xFF0C].startswith("uniFF0C") and cmap[97] == "uni0061"
    assert [m.codepoints for m in report.materials] == [5, 2]
    assert report.materials[1].groups == ["han", "cjk_symbols"]
    assert stages[0] == "plan" and stages[-1] == "done" and "merge" in stages


def test_forge_single_material_with_bold_and_scale(font_dir, tmp_path):
    (a,) = faces(font_dir, "A.ttf")
    spec = ForgeSpec(materials=[MaterialSpec(a, weight=700, scale=0.5)], style_name="Bold")
    report = forge(spec, tmp_path / "x.ttf")
    f = TTFont(str(tmp_path / "x.ttf"))
    assert f["OS/2"].usWeightClass == 700 and f["head"].macStyle & 1 and f["OS/2"].fsSelection & (1 << 5)
    assert f["hmtx"]["uni0061"][0] == 130  # (200 * 0.5) + 30 stroke
    assert report.materials[0].warnings == ["synthetic bold (+300)"]


def test_forge_restricted_licence_is_a_warning(font_dir, tmp_path):
    (c,) = faces(font_dir, "C.ttf")
    report = forge(ForgeSpec(materials=[MaterialSpec(c)]), tmp_path / "c.ttf")
    assert any("restricted" in w for w in report.materials[0].warnings)
    assert TTFont(str(tmp_path / "c.ttf"))["head"].unitsPerEm == 2048


def test_forge_validation_error(tmp_path):
    with pytest.raises(ForgeError) as e:
        forge(ForgeSpec(), tmp_path / "n.ttf")
    assert e.value.stage == "validate"


def _pairpos_values(font):
    """{(left, right): XAdvance} from every GPOS PairPos format-1 subtable."""
    out = {}
    if "GPOS" not in font:
        return out
    for lookup in font["GPOS"].table.LookupList.Lookup:
        for st in lookup.SubTable:
            if getattr(st, "Format", None) != 1 or st.LookupType != 2:
                continue
            for left, pairset in zip(st.Coverage.glyphs, st.PairSet):
                for rec in pairset.PairValueRecord:
                    out[(left, rec.SecondGlyph)] = rec.Value1.XAdvance
    return out


def test_forge_old_os2_only_material(font_dir, tmp_path):
    (k,) = faces(font_dir, "K.ttf")
    forge(ForgeSpec(materials=[MaterialSpec(k)]), tmp_path / "k.ttf")
    os2 = TTFont(str(tmp_path / "k.ttf"))["OS/2"]
    assert os2.version >= 4 and os2.sxHeight == 0 and os2.usBreakChar == 32 and os2.fsSelection & (1 << 7)


def test_forge_non_ascii_family_name(font_dir, tmp_path):
    (a,) = faces(font_dir, "A.ttf")
    forge(ForgeSpec(materials=[MaterialSpec(a)], family_name="合体字体"), tmp_path / "cjk.ttf")
    name = TTFont(str(tmp_path / "cjk.ttf"))["name"]
    assert name.getDebugName(1) == "合体字体" and name.getDebugName(6) == "Forged-Regular"
    assert name.getName(1, 1, 0, 0) is None  # no Mac Roman record for a string it cannot encode


def test_legacy_kern_survives_as_gpos(font_dir, tmp_path):
    (k,) = faces(font_dir, "K.ttf")
    forge(ForgeSpec(materials=[MaterialSpec(k)]), tmp_path / "kern.ttf")
    f = TTFont(str(tmp_path / "kern.ttf"))
    assert "kern" not in f
    assert any(r.FeatureTag == "kern" for r in f["GPOS"].table.FeatureList.FeatureRecord)
    assert _pairpos_values(f)[("uni0061", "uni0062")] == -50
    scripts = {sr.ScriptTag for sr in f["GPOS"].table.ScriptList.ScriptRecord}
    assert {"DFLT", "latn"} <= scripts


def test_validate_rejects_scale_that_overflows_upem(font_dir):
    (c,) = faces(font_dir, "C.ttf")  # 2048 upem
    errors = ForgeSpec(materials=[MaterialSpec(c, scale=9.0)]).validate()
    assert errors and "too large" in errors[0]
    assert ForgeSpec(materials=[MaterialSpec(c, scale=8.0)]).validate() == []
