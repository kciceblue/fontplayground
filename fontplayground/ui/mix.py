"""A mix: the fonts of a recipe with their resolved adjustments and script rules — what the preview draws.

The model hands out a Mix for the current recipe (ForgeModel.mix) or for a recipe with one font tried in
(ForgeModel.mix_with). Which font draws a character is planner.source_of, the very rule the build uses.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property

from fontplayground.catalog.face import FontFace
from fontplayground.engine.planner import source_of

FaceKey = tuple[str, int]


@dataclass(frozen=True)
class MixFont:
    face: FontFace
    weight: int | None = None    # boldness to draw it at; None: as it is
    scale: float = 1.0


@dataclass(frozen=True)
class Mix:
    fonts: tuple[MixFont, ...] = ()
    rules: Mapping[str, int | None] = field(default_factory=dict)   # script group -> font index (ForgeSpec rules)
    base_index: int = 0                                             # the font whose line spacing the result takes

    def keys(self) -> list[FaceKey]:
        return [f.face.key for f in self.fonts]

    @cached_property
    def _sets(self) -> list[frozenset[int]]:
        return [f.face.codepoints for f in self.fonts]

    def source_of(self, cp: int) -> int | None:
        """Index of the font that draws `cp`, None when no font has it."""
        return source_of(cp, self._sets, self.rules)


EMPTY_MIX = Mix()
