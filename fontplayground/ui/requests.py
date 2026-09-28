"""What the recipe asks of the font picker. Shared by the recipe panel, the picker and the main window."""
from __future__ import annotations

from dataclasses import dataclass

FaceKey = tuple[str, int]


@dataclass(frozen=True)
class PickRequest:
    language: str                        # languages id: what the picker lists (and what an added font is for)
    replace_key: FaceKey | None = None   # the font being replaced (Change…); None adds a font
