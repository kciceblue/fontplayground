"""Turn one material into a merge-ready TrueType part."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.varLib.instancer import instantiateVariableFont

from fontplayground.engine.kern import kern_to_gpos
from fontplayground.engine.spec import ForgeError, MaterialSpec
from fontplayground.engine.synth_bold import MAX_DELTA, embolden

KEEP_TABLES = {"head", "hhea", "maxp", "OS/2", "hmtx", "cmap", "loca", "glyf", "name", "post", "GSUB", "GPOS", "GDEF", "kern"}
MAX_UPEM = 16384


@dataclass
class PreparedFont:
    path: str
    upem: int
    warnings: list[str] = field(default_factory=list)


def load_face(material: MaterialSpec) -> TTFont:
    face = material.face
    return TTFont(face.path, fontNumber=face.index if face.is_collection else -1)


def instance_variable(font: TTFont, weight: int | None) -> TTFont:
    fvar = font["fvar"]
    limits = {a.axisTag: a.defaultValue for a in fvar.axes}
    if weight is not None and "wght" in limits:
        a = next(a for a in fvar.axes if a.axisTag == "wght")
        limits["wght"] = min(max(weight, a.minValue), a.maxValue)
    return instantiateVariableFont(font, limits, inplace=False)


def subset_options() -> Options:
    o = Options()
    o.layout_features = ["*"]
    o.hinting = False
    o.notdef_outline = True
    o.glyph_names = True
    o.desubroutinize = True
    o.name_IDs = ["*"]
    o.name_legacy = True
    o.name_languages = ["*"]
    o.drop_tables = list(o.drop_tables) + ["DSIG"]
    return o


DROPPED_FEATURES = {"locl"}  # per-language variants are out of scope; keeping them adds ~18k glyphs to pan-CJK fonts


def kept_features(font: TTFont) -> list[str]:
    """Every OpenType feature the font has, minus DROPPED_FEATURES (so the closure stays small)."""
    tags: set[str] = set()
    for table in ("GSUB", "GPOS"):
        if table in font and font[table].table.FeatureList:
            tags |= {r.FeatureTag for r in font[table].table.FeatureList.FeatureRecord}
    return sorted(tags - DROPPED_FEATURES)


def subset_font(font: TTFont, codepoints) -> None:
    options = subset_options()
    options.layout_features = kept_features(font)
    s = Subsetter(options)
    s.populate(unicodes=sorted(codepoints))
    s.subset(font)


def cff_to_glyf(font: TTFont) -> None:
    """Replace CFF outlines with TrueType quadratic outlines (fontTools otf2ttf recipe)."""
    upem = font["head"].unitsPerEm
    glyph_set = font.getGlyphSet()
    order = font.getGlyphOrder()
    glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = {}
    for name in order:
        tt_pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(tt_pen, max_err=upem / 1000, reverse_direction=True))
        glyf.glyphs[name] = tt_pen.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)
    hmtx = font["hmtx"]
    for name, g in glyf.glyphs.items():
        if hasattr(g, "xMin"):
            hmtx[name] = (hmtx[name][0], g.xMin)
    maxp = font["maxp"] = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones = 1
    maxp.maxTwilightPoints = maxp.maxStorage = maxp.maxFunctionDefs = maxp.maxInstructionDefs = 0
    maxp.maxStackElements = maxp.maxSizeOfInstructions = 0
    maxp.maxComponentElements = max((len(getattr(g, "components", [])) for g in glyf.glyphs.values()), default=0)
    maxp.compile(font)
    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order
    try:
        post.compile(font)
    except OverflowError:
        post.formatType = 3
    font.sfntVersion = "\x00\x01\x00\x00"


def scale_font(font: TTFont, target_upem: int, scale: float) -> None:
    """Scale outlines and metrics by `scale`, expressed in `target_upem` units."""
    new_upem = round(target_upem * scale)
    if font["head"].unitsPerEm != new_upem:
        scale_upem(font, new_upem)
    font["head"].unitsPerEm = target_upem


def strip_tables(font: TTFont) -> None:
    for tag in list(font.keys()):
        if tag != "GlyphOrder" and tag not in KEEP_TABLES:
            del font[tag]


def prepare(material: MaterialSpec, codepoints, target_upem: int, weight: int | None, scale: float,
            workdir: Path, index: int) -> PreparedFont:
    face = material.face
    warnings: list[str] = []
    font = load_face(material)
    if face.is_variable:
        try:
            font = instance_variable(font, weight)
        except Exception:
            # Some system fonts (e.g. Segoe UI Variable) carry GPOS variation indices that point
            # outside their VarStore; fontTools cannot instance those. Retry without GPOS.
            font.close()
            font = load_face(material)
            if "GPOS" in font:
                del font["GPOS"]
            try:
                font = instance_variable(font, weight)
            except Exception as e:
                raise ForgeError("prepare", face.display_name,
                                 f"cannot instance this variable font: {type(e).__name__}: {e}") from e
            warnings.append("GPOS dropped: the font's variable positioning data is broken, "
                            "so kerning and mark positioning are lost")
    subset_font(font, codepoints)
    kern_to_gpos(font)  # legacy 'kern' would be dropped by the merger; GPOS survives
    if face.outline == "CFF":
        cff_to_glyf(font)
    # Synthetic bold runs in the material's own units, before scaling, so the extra
    # stem thickness shrinks or grows together with the glyphs.
    if weight is not None and not face.has_wght_axis:
        delta = weight - face.weight_class
        if delta >= 50:
            embolden(font, delta)
            warnings.append(f"synthetic bold (+{min(delta, MAX_DELTA)})")
        elif delta <= -50:
            warnings.append("cannot make lighter than source; weight left as is")
    scale_font(font, target_upem, scale)
    strip_tables(font)
    out = Path(workdir) / f"{index}.ttf"
    try:
        font.save(str(out))
    except (struct.error, OverflowError, ValueError) as e:
        raise ForgeError("prepare", face.display_name,
                         f"scale {scale * 100:g}% pushes this font's coordinates past the TrueType limit; "
                         f"use a smaller scale ({type(e).__name__}: {e})") from e
    finally:
        font.close()
    return PreparedFont(str(out), target_upem, warnings)
