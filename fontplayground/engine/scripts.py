"""Script groups used for the forge's language rules."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from fontTools.unicodedata import script


@dataclass(frozen=True)
class ScriptGroup:
    id: str
    label: str


GROUPS: list[ScriptGroup] = [
    ScriptGroup("latin", "Latin"),
    ScriptGroup("greek", "Greek"),
    ScriptGroup("cyrillic", "Cyrillic"),
    ScriptGroup("armenian_georgian", "Armenian & Georgian"),
    ScriptGroup("hebrew", "Hebrew"),
    ScriptGroup("arabic", "Arabic"),
    ScriptGroup("indic", "Indic"),
    ScriptGroup("southeast_asian", "Thai, Lao, Khmer, Myanmar"),
    ScriptGroup("hangul", "Hangul"),
    ScriptGroup("kana", "Kana"),
    ScriptGroup("han", "Han"),
    ScriptGroup("cjk_symbols", "CJK symbols & fullwidth"),
    ScriptGroup("symbols", "Punctuation & symbols"),
    ScriptGroup("emoji", "Emoji & pictographs"),
    ScriptGroup("other", "Everything else"),
]
GROUP_IDS = [g.id for g in GROUPS]
LABELS = {g.id: g.label for g in GROUPS}

_CJK_SYMBOL_RANGES = ((0x3000, 0x303F), (0x3200, 0x33FF), (0xFE30, 0xFE4F), (0xFF00, 0xFFEF))
_COMMON = {"Zyyy", "Zinh"}
_SCRIPT_TO_GROUP = {
    "Latn": "latin", "Grek": "greek", "Cyrl": "cyrillic",
    "Armn": "armenian_georgian", "Geor": "armenian_georgian",
    "Hebr": "hebrew", "Arab": "arabic",
    "Deva": "indic", "Beng": "indic", "Guru": "indic", "Gujr": "indic", "Orya": "indic",
    "Taml": "indic", "Telu": "indic", "Knda": "indic", "Mlym": "indic", "Sinh": "indic",
    "Thai": "southeast_asian", "Laoo": "southeast_asian", "Khmr": "southeast_asian", "Mymr": "southeast_asian",
    "Hang": "hangul", "Hira": "kana", "Kana": "kana", "Hani": "han", "Bopo": "han",
}


@lru_cache(maxsize=None)
def group_of(cp: int) -> str:
    """Return the group id for a code point. Rules are ordered; first match wins."""
    for lo, hi in _CJK_SYMBOL_RANGES:
        if lo <= cp <= hi:
            return "cjk_symbols"
    if 0x1F000 <= cp <= 0x1FAFF:
        return "emoji"
    sc = script(chr(cp))
    if sc in _COMMON:
        if cp <= 0x024F:
            return "latin"
        return "symbols" if cp < 0x1F000 else "other"
    return _SCRIPT_TO_GROUP.get(sc, "other")


def groups_covered(codepoints) -> list[str]:
    """Group ids (in GROUPS order) that have at least one code point in the set."""
    found = {group_of(cp) for cp in codepoints}
    return [g for g in GROUP_IDS if g in found]
