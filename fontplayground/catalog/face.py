"""FontFace metadata and reading it from font files."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

from fontplayground.engine.scripts import groups_covered

COLOR_TABLES = ("COLR", "CBDT", "sbix", "SVG ")


@dataclass(frozen=True)
class FontFace:
    path: str
    index: int
    family: str
    style: str
    outline: str  # "glyf" | "CFF" | "CFF2" | "none"
    is_collection: bool
    is_variable: bool
    axes: tuple[tuple[str, float, float, float], ...]
    weight_class: int
    italic: bool
    upem: int
    glyph_count: int
    codepoints: frozenset[int]
    embedding: str  # "installable" | "editable" | "preview-print" | "restricted"
    has_color: bool
    size: int
    mtime: float

    @property
    def key(self) -> tuple[str, int]:
        return (self.path, self.index)

    @property
    def display_name(self) -> str:
        return f"{self.family} {self.style}"

    @property
    def format_tag(self) -> str:
        if self.is_variable:
            return "VAR"
        if self.is_collection:
            return "TTC"
        return "OTF" if self.outline.startswith("CFF") else "TTF"

    @property
    def has_wght_axis(self) -> bool:
        return any(a[0] == "wght" for a in self.axes)

    @property
    def unsupported_reason(self) -> str | None:
        if self.outline == "none":
            return "bitmap-only font (no outlines)"
        if self.outline == "CFF2":
            return "CFF2 outlines are not supported"
        if self.has_color:
            return "colour fonts are not supported"
        return None

    @property
    def supported(self) -> bool:
        return self.unsupported_reason is None

    @cached_property
    def scripts(self) -> list[str]:
        return groups_covered(self.codepoints)


def _embedding(fs_type: int) -> str:
    if fs_type & 0x0002:
        return "restricted"
    if fs_type & 0x0004:
        return "preview-print"
    if fs_type & 0x0008:
        return "editable"
    return "installable"


def _name_rank(record) -> int | None:
    """Rank of a name record whose text decodes reliably, lower first; None for records left to fontTools."""
    if record.platformID == 3 and record.platEncID in (0, 1, 10):  # Windows Unicode, what Windows itself shows
        return 0 if record.langID == 0x409 else 1
    if (record.platformID, record.platEncID) == (1, 1):  # Mac Japanese, which fontTools decodes as Shift-JIS
        return 2
    return None


def _best_name(name, name_ids) -> str | None:
    """The first of name_ids that has a name, read from its most reliably decoded record.

    fontTools' getBestFamilyName takes any Mac record labelled English first, but some Japanese fonts (EPSON's) keep
    Shift-JIS bytes in Mac Roman records, which then read as mojibake. Ranked records come first; the rest are left
    to fontTools.
    """
    for name_id in name_ids:
        ranked = [r for r in name.names if r.nameID == name_id and _name_rank(r) is not None]
        for record in sorted(ranked, key=_name_rank):
            try:
                text = record.toUnicode()
            except UnicodeDecodeError:
                continue
            if text:
                return text
        text = name.getDebugName(name_id)
        if text:
            return text
    return None


def _face(font: TTFont, path: Path, index: int, is_collection: bool, size: int, mtime: float) -> FontFace:
    name = font["name"]
    fvar = font["fvar"] if "fvar" in font else None
    os2 = font["OS/2"] if "OS/2" in font else None
    if "glyf" in font:
        outline = "glyf"
    elif "CFF " in font:
        outline = "CFF"
    elif "CFF2" in font:
        outline = "CFF2"
    else:
        outline = "none"
    return FontFace(
        path=str(path), index=index,
        family=_best_name(name, (21, 16, 1)) or path.stem,
        style=_best_name(name, (22, 17, 2)) or "Regular",
        outline=outline, is_collection=is_collection, is_variable=fvar is not None,
        axes=tuple((a.axisTag, float(a.minValue), float(a.defaultValue), float(a.maxValue)) for a in fvar.axes) if fvar else (),
        weight_class=int(os2.usWeightClass) if os2 else 400,
        italic=bool(os2.fsSelection & 1) if os2 else bool(font["head"].macStyle & 2),
        upem=int(font["head"].unitsPerEm), glyph_count=int(font["maxp"].numGlyphs),
        codepoints=frozenset(font.getBestCmap() or {}),
        embedding=_embedding(int(os2.fsType)) if os2 else "installable",
        has_color=any(t in font for t in COLOR_TABLES), size=size, mtime=mtime,
    )


def read_faces(path: str | Path) -> list[FontFace]:
    """Read every face in a font file. Raises on unreadable files."""
    p = Path(path)
    st = p.stat()
    if p.suffix.lower() in (".ttc", ".otc"):
        coll = TTCollection(str(p), lazy=True)
        try:
            return [_face(f, p, i, True, st.st_size, st.st_mtime) for i, f in enumerate(coll.fonts)]
        finally:
            coll.close()
    font = TTFont(str(p), lazy=True)
    try:
        return [_face(font, p, 0, False, st.st_size, st.st_mtime)]
    finally:
        font.close()
