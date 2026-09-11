"""Merge prepared parts into one font, then set names, metrics and flags."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from fontTools.merge import Merger
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont

from fontplayground.engine.prepare import subset_options
from fontplayground.engine.spec import ForgeError, ForgeSpec

STANDARD_STYLES = {"Regular", "Bold", "Italic", "Bold Italic"}
MAX_GLYPHS = 65535
LEFTOVER_TABLES = ("DSIG", "fpgm", "prep", "cvt ")


def merge_fonts(paths: list[str]) -> TTFont:
    return Merger().merge(paths)


def final_subset(font: TTFont, codepoints) -> None:
    """Drop every glyph not reachable from the planned code points (e.g. a duplicate .notdef)."""
    s = Subsetter(subset_options())
    s.populate(unicodes=sorted(codepoints))
    s.subset(font)


def postscript_name(family: str, style: str) -> str:
    fam = re.sub(r"[^A-Za-z0-9]", "", family)
    sty = re.sub(r"[^A-Za-z0-9]", "", style)
    return f"{fam}-{sty}"[:63]


def set_names(font: TTFont, family: str, style: str, sources: list[str]) -> None:
    name = font["name"]
    name.names = []
    full = f"{family} {style}"
    records = {
        0: "Forged with Font Playground from: " + ", ".join(sources),
        3: f"{full}; FontPlayground {date.today().isoformat()}",
        4: full,
        5: "Version 1.000",
        6: postscript_name(family, style),
    }
    if style in STANDARD_STYLES:
        records[1], records[2] = family, style
    else:
        legacy = "Bold" if "bold" in style.lower() else "Regular"
        if "italic" in style.lower() or "oblique" in style.lower():
            legacy = "Bold Italic" if legacy == "Bold" else "Italic"
        records[1], records[2], records[16], records[17] = full, legacy, family, style
    for nid, value in records.items():
        name.setName(value, nid, 3, 1, 0x409)
        name.setName(value, nid, 1, 0, 0)


def set_style_bits(font: TTFont, style: str) -> None:
    s = style.lower()
    bold, italic = "bold" in s, ("italic" in s or "oblique" in s)
    font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
    os2 = font["OS/2"]
    sel = os2.fsSelection & ~((1 << 0) | (1 << 5) | (1 << 6))
    if italic:
        sel |= 1 << 0
    if bold:
        sel |= 1 << 5
    if not bold and not italic:
        sel |= 1 << 6
    os2.fsSelection = sel | (1 << 7)  # USE_TYPO_METRICS


def copy_vertical_metrics(font: TTFont, base: TTFont) -> None:
    for attr in ("ascent", "descent", "lineGap"):
        setattr(font["hhea"], attr, getattr(base["hhea"], attr))
    for attr in ("sTypoAscender", "sTypoDescender", "sTypoLineGap", "usWinAscent", "usWinDescent"):
        setattr(font["OS/2"], attr, getattr(base["OS/2"], attr))
    for attr in ("sxHeight", "sCapHeight"):
        if hasattr(base["OS/2"], attr) and hasattr(font["OS/2"], attr):
            setattr(font["OS/2"], attr, getattr(base["OS/2"], attr))


def finish(font: TTFont, spec: ForgeSpec, base: TTFont, codepoints, weight_class: int) -> None:
    final_subset(font, codepoints)
    set_names(font, spec.family_name.strip(), spec.style_name.strip(), [m.face.display_name for m in spec.materials])
    set_style_bits(font, spec.style_name)
    copy_vertical_metrics(font, base)
    os2 = font["OS/2"]
    os2.usWeightClass = weight_class
    os2.fsType = 0
    os2.recalcUnicodeRanges(font)
    os2.recalcCodePageRanges(font)
    for tag in LEFTOVER_TABLES:
        if tag in font:
            del font[tag]


def verify(path: Path, codepoints: set[int]) -> tuple[int, int]:
    """Reload the saved font and check coverage. Returns (code points, glyphs)."""
    font = TTFont(str(path))
    try:
        got = set(font.getBestCmap() or {})
        missing, extra = codepoints - got, got - codepoints
        if missing or extra:
            raise ForgeError("verify", None, f"coverage mismatch: {len(missing)} missing, {len(extra)} unexpected")
        glyphs = font["maxp"].numGlyphs
        if glyphs > MAX_GLYPHS:
            raise ForgeError("verify", None, f"{glyphs} glyphs exceed the TrueType limit of {MAX_GLYPHS}")
        return len(got), glyphs
    finally:
        font.close()
