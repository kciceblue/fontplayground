"""Decide which material supplies each code point."""
from __future__ import annotations

from collections.abc import Container, Mapping, Sequence

from fontplayground.engine.scripts import group_of
from fontplayground.engine.spec import ForgeSpec, Plan


def source_of(cp: int, codepoint_sets: Sequence[Container[int]], rules: Mapping[str, int | None]) -> int | None:
    """The material that draws `cp`: the rule's material for the character's script group when it has the character,
    else the first material (priority order) that has it; None when none does. plan() and the preview both use it."""
    chosen = rules.get(group_of(cp))
    if chosen is not None and 0 <= chosen < len(codepoint_sets) and cp in codepoint_sets[chosen]:
        return chosen
    return next((i for i, cps in enumerate(codepoint_sets) if cp in cps), None)


def plan(spec: ForgeSpec) -> Plan:
    sets = [m.face.codepoints for m in spec.materials]
    assignments: dict[int, set[int]] = {i: set() for i in range(len(sets))}
    source: dict[int, int] = {}
    for cp in set().union(*sets) if sets else ():
        chosen = source_of(cp, sets, spec.script_rules)
        assignments[chosen].add(cp)
        source[cp] = chosen
    return Plan(assignments, source)
