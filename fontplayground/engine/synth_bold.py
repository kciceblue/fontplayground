"""Fake bold: stroke every outline and union it with the fill."""
from __future__ import annotations

import pathops
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

MAX_DELTA = 500


def stroke_width(delta_weight: int, upem: int) -> float:
    """+300 weight on a 1000-upem font thickens stems by 60 units."""
    return delta_weight / 1000 * 0.2 * upem


def embolden(font: TTFont, delta_weight: int) -> None:
    delta = min(delta_weight, MAX_DELTA)
    glyf, hmtx = font["glyf"], font["hmtx"]
    glyph_set = font.getGlyphSet()
    w = stroke_width(delta, font["head"].unitsPerEm)
    for name in font.getGlyphOrder():
        path = pathops.Path()
        glyph_set[name].draw(path.getPen(glyphSet=glyph_set))  # decomposes components
        if not list(path.contours):
            continue
        stroked = pathops.Path(path)
        stroked.stroke(w, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4.0)
        stroked.convertConicsToQuads()
        result = pathops.op(path, stroked, pathops.PathOp.UNION)
        result.convertConicsToQuads()
        result = result.transform(translateX=w / 2)  # keep the left side bearing
        pen = TTGlyphPen(None)
        result.draw(pen)
        glyph = pen.glyph()
        glyph.recalcBounds(glyf)
        glyf.glyphs[name] = glyph
        advance, _ = hmtx[name]
        hmtx[name] = (advance + round(w), glyph.xMin)
    font["hhea"].advanceWidthMax = max(a for a, _ in hmtx.metrics.values())
