"""Data model for a forge run: inputs, plan, reports and errors."""
from __future__ import annotations

from dataclasses import dataclass, field

from fontplayground.catalog.face import FontFace


class ForgeError(Exception):
    def __init__(self, stage: str, material: str | None, message: str):
        self.stage, self.material, self.message = stage, material, message
        where = f"{stage} ({material})" if material else stage
        super().__init__(f"[{where}] {message}")


@dataclass
class MaterialSpec:
    face: FontFace
    weight: int | None = None   # None -> ForgeSpec.default_weight
    scale: float | None = None  # None -> ForgeSpec.default_scale


@dataclass
class ForgeSpec:
    materials: list[MaterialSpec] = field(default_factory=list)  # priority order
    base_index: int = 0
    script_rules: dict[str, int | None] = field(default_factory=dict)  # group id -> material index
    default_weight: int | None = None  # None -> "as is"
    default_scale: float = 1.0
    family_name: str = "Forged"
    style_name: str = "Regular"

    def resolved_weight(self, i: int) -> int | None:
        w = self.materials[i].weight
        return w if w is not None else self.default_weight

    def resolved_scale(self, i: int) -> float:
        s = self.materials[i].scale
        return s if s is not None else self.default_scale

    def validate(self) -> list[str]:
        errors: list[str] = []
        n = len(self.materials)
        if n == 0:
            return ["Add at least one material."]
        if not 0 <= self.base_index < n:
            errors.append("Base material is out of range.")
        for m in self.materials:
            if not m.face.supported:
                errors.append(f"{m.face.display_name}: {m.face.unsupported_reason}")
        if not self.family_name.strip():
            errors.append("Family name is empty.")
        if not self.style_name.strip():
            errors.append("Style name is empty.")
        for g, idx in self.script_rules.items():
            if idx is not None and not 0 <= idx < n:
                errors.append(f"Rule for {g} points to a missing material.")
        for i, m in enumerate(self.materials):
            s = self.resolved_scale(i)
            if not 0.1 <= s <= 10:
                errors.append(f"{m.face.display_name}: scale {s:g} must be between 0.1 and 10.")
            w = self.resolved_weight(i)
            if w is not None and not 1 <= w <= 1000:
                errors.append(f"{m.face.display_name}: weight {w} must be between 1 and 1000.")
        return errors

    def to_dict(self) -> dict:
        return {
            "materials": [{"path": m.face.path, "index": m.face.index, "weight": m.weight, "scale": m.scale}
                          for m in self.materials],
            "base_index": self.base_index,
            "script_rules": dict(self.script_rules),
            "default_weight": self.default_weight,
            "default_scale": self.default_scale,
            "family_name": self.family_name,
            "style_name": self.style_name,
        }

    @classmethod
    def from_dict(cls, d: dict, faces_by_key: dict[tuple[str, int], FontFace]) -> "ForgeSpec":
        materials, remap = [], {}
        for old, m in enumerate(d.get("materials", [])):
            face = faces_by_key.get((m["path"], m["index"]))
            if face is None:
                continue
            remap[old] = len(materials)
            materials.append(MaterialSpec(face, m.get("weight"), m.get("scale")))
        rules = {g: (remap.get(idx) if idx is not None else None) for g, idx in d.get("script_rules", {}).items()}
        return cls(materials=materials, base_index=remap.get(d.get("base_index", 0), 0), script_rules=rules,
                   default_weight=d.get("default_weight"), default_scale=d.get("default_scale", 1.0),
                   family_name=d.get("family_name", "Forged"), style_name=d.get("style_name", "Regular"))


@dataclass
class Plan:
    assignments: dict[int, set[int]]  # material index -> code points (disjoint)
    source: dict[int, int]            # code point -> material index


@dataclass
class MaterialReport:
    name: str
    codepoints: int
    groups: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ForgeReport:
    materials: list[MaterialReport]
    total_codepoints: int
    total_glyphs: int
    warnings: list[str]
    output_path: str

    def as_text(self) -> str:
        from fontplayground.engine.scripts import LABELS
        lines = [f"Output: {self.output_path}", f"Characters: {self.total_codepoints}   Glyphs: {self.total_glyphs}", ""]
        for m in self.materials:
            groups = ", ".join(LABELS.get(g, g) for g in m.groups) or "-"
            lines.append(f"{m.name}: {m.codepoints} characters  [{groups}]")
            lines += [f"    warning: {w}" for w in m.warnings]
        if self.warnings:
            lines += ["", "Warnings:"] + [f"  - {w}" for w in self.warnings]
        return "\n".join(lines)
