from fontplayground.engine.planner import plan
from fontplayground.engine.spec import ForgeSpec, MaterialSpec
from fontplayground.ui.mix import EMPTY_MIX, Mix, MixFont
from tests.fixtures import cps, fake_face

A = fake_face(cps("abc1,"), path="a.ttf", family="A")
B = fake_face(cps("ab漢，"), path="b.ttf", family="B")


def test_source_of_agrees_with_the_plan():
    rules = {"latin": 1, "han": 1}
    mix = Mix((MixFont(A), MixFont(B)), rules)
    p = plan(ForgeSpec(materials=[MaterialSpec(A), MaterialSpec(B)], script_rules=rules))
    for cp in A.codepoints | B.codepoints:
        assert mix.source_of(cp) == p.source[cp]
    assert mix.source_of(ord("한")) is None


def test_mix_basics():
    mix = Mix((MixFont(A, 700, 0.9), MixFont(B)), {}, base_index=1)
    assert mix.keys() == [A.key, B.key] and mix.fonts[0].weight == 700 and mix.fonts[1].scale == 1.0
    assert mix.base_index == 1 and mix == Mix((MixFont(A, 700, 0.9), MixFont(B)), {}, base_index=1)
    assert EMPTY_MIX.fonts == () and EMPTY_MIX.source_of(ord("a")) is None and EMPTY_MIX.keys() == []
