from fontplayground.engine.planner import plan, source_of
from fontplayground.engine.spec import ForgeSpec, MaterialSpec
from tests.fixtures import cps, fake_face

A = fake_face(cps("abc1"), path="a.ttf", family="A")
B = fake_face(cps("ab漢，"), path="b.ttf", family="B")


def test_priority_order_wins_without_rules():
    p = plan(ForgeSpec(materials=[MaterialSpec(A), MaterialSpec(B)]))
    assert p.assignments[0] == cps("abc1") and p.assignments[1] == cps("漢，")
    assert p.source[ord("a")] == 0


def test_rule_overrides_priority():
    p = plan(ForgeSpec(materials=[MaterialSpec(A), MaterialSpec(B)], script_rules={"latin": 1}))
    assert p.assignments[1] == cps("ab漢，") and p.assignments[0] == cps("c1")


def test_rule_falls_back_when_material_lacks_char():
    p = plan(ForgeSpec(materials=[MaterialSpec(B), MaterialSpec(A)], script_rules={"han": 1}))
    assert p.source[ord("漢")] == 0  # A has no Han, so priority order decides


def test_assignments_are_disjoint_and_complete():
    p = plan(ForgeSpec(materials=[MaterialSpec(A), MaterialSpec(B)]))
    assert p.assignments[0].isdisjoint(p.assignments[1])
    assert p.assignments[0] | p.assignments[1] == A.codepoints | B.codepoints == set(p.source)


def test_source_of_prefers_the_rule_font_when_it_has_the_character():
    sets = [cps("a漢"), cps("a漢b")]
    assert source_of(ord("漢"), sets, {"han": 1}) == 1
    assert source_of(ord("a"), sets, {"han": 1}) == 0          # no rule for latin: the first font that has it


def test_source_of_falls_back_to_priority_order_then_none():
    sets = [cps("a"), cps("漢")]
    assert source_of(ord("漢"), sets, {"han": 0}) == 1          # the rule's font lacks it
    assert source_of(ord("한"), sets, {}) is None
    assert source_of(ord("a"), sets, {"latin": 7}) == 0         # an out-of-range rule is ignored
