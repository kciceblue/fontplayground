"""Small text helpers shared by the UI layer."""
from __future__ import annotations

import unicodedata

# Code points that never show as a glyph of their own: joiners, variation selectors, bidi controls, soft hyphen…
_IGNORABLE_RANGES = ((0x200B, 0x200F), (0x2028, 0x202E), (0x2060, 0x206F), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
                     (0x00AD, 0x00AD), (0xE0100, 0xE01EF), (0x180B, 0x180E), (0x034F, 0x034F))


def is_ignorable(char: str) -> bool:
    """True for whitespace and default-ignorable characters that should never count as 'missing'."""
    if char.isspace():
        return True
    cp = ord(char)
    if any(lo <= cp <= hi for lo, hi in _IGNORABLE_RANGES):
        return True
    return unicodedata.category(char) in ("Cf", "Cc", "Cn")


def visible_chars(text: str) -> list[str]:
    """Sorted unique characters of `text` that can show as glyphs."""
    return sorted({c for c in text if not is_ignorable(c)})
