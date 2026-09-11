"""Decide which material supplies each code point."""
from __future__ import annotations

from fontplayground.engine.scripts import group_of
from fontplayground.engine.spec import ForgeSpec, Plan


def plan(spec: ForgeSpec) -> Plan:
    materials = spec.materials
    assignments: dict[int, set[int]] = {i: set() for i in range(len(materials))}
    source: dict[int, int] = {}
    all_cps: set[int] = set().union(*(m.face.codepoints for m in materials)) if materials else set()
    for cp in all_cps:
        chosen = spec.script_rules.get(group_of(cp))
        if chosen is None or cp not in materials[chosen].face.codepoints:
            chosen = next(i for i, m in enumerate(materials) if cp in m.face.codepoints)
        assignments[chosen].add(cp)
        source[cp] = chosen
    return Plan(assignments, source)
