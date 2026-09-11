from fontplayground.engine.spec import ForgeSpec, MaterialSpec
from tests.fixtures import cps, fake_face


def make_spec():
    a = fake_face(cps("abc"), path="a.ttf", family="A")
    b = fake_face(cps("ab漢"), path="b.otf", family="B", weight=700)
    return ForgeSpec(materials=[MaterialSpec(a), MaterialSpec(b, weight=500, scale=0.9)],
                     script_rules={"han": 1, "latin": None}, default_weight=None, default_scale=1.0)


def test_resolution():
    s = make_spec()
    assert s.resolved_weight(0) is None and s.resolved_weight(1) == 500
    assert s.resolved_scale(0) == 1.0 and s.resolved_scale(1) == 0.9
    s.default_weight = 300
    assert s.resolved_weight(0) == 300


def test_validate_ok_and_errors():
    assert make_spec().validate() == []
    bad = make_spec()
    bad.family_name = " "; bad.base_index = 5; bad.script_rules["greek"] = 9
    bad.materials.append(MaterialSpec(fake_face({97}, outline="none", family="Bmp")))
    errors = bad.validate()
    assert any("Family name" in e for e in errors) and any("Base" in e for e in errors)
    assert any("greek" in e for e in errors) and any("bitmap" in e for e in errors)
    assert ForgeSpec().validate() == ["Add at least one material."]


def test_json_roundtrip_and_missing_face():
    s = make_spec()
    d = s.to_dict()
    faces = {m.face.key: m.face for m in s.materials}
    back = ForgeSpec.from_dict(d, faces)
    assert [m.face.key for m in back.materials] == [m.face.key for m in s.materials]
    assert back.materials[1].weight == 500 and back.script_rules == {"han": 1, "latin": None}
    # drop material 0: indices shift, rules pointing at it are cleared
    s.base_index = 1
    back2 = ForgeSpec.from_dict(s.to_dict(), {s.materials[1].face.key: s.materials[1].face})
    assert len(back2.materials) == 1 and back2.script_rules["han"] == 0 and back2.base_index == 0
