"""Build tiny fonts for tests. No external font files needed."""
from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection, TTFont, newTable
from fontTools.ttLib.tables._k_e_r_n import KernTable_format_0
from fontTools.ttLib.tables.TupleVariation import TupleVariation

from fontplayground.catalog.face import FontFace

STEM, HEIGHT, LSB = 100, 700, 50


def glyph_name(cp: int) -> str:
    return f"uni{cp:04X}"


def _rect(pen, x0, y0, x1, y1):
    pen.moveTo((x0, y0))
    pen.lineTo((x1, y0))
    pen.lineTo((x1, y1))
    pen.lineTo((x0, y1))
    pen.closePath()


def build_font(path, family, style, codepoints, *, upem=1000, cff=False, weight=400, fs_type=0, variable=False,
               os2_version=None, composites=None, kern=None) -> Path:
    """Every glyph is a rectangle from x=LSB to LSB+STEM, y=0..HEIGHT, advance STEM+2*LSB (scaled by upem/1000).

    composites: {codepoint: base_codepoint} adds TrueType composite glyphs (after the simple ones in glyph order).
    kern: {(left_cp, right_cp): value} adds a legacy format-0 'kern' table.
    """
    k = upem / 1000
    stem, height, lsb = round(STEM * k), round(HEIGHT * k), round(LSB * k)
    advance = stem + 2 * lsb
    composites = composites or {}
    simple = [glyph_name(cp) for cp in sorted(codepoints)]
    order = [".notdef"] + simple + [glyph_name(cp) for cp in sorted(composites)]
    fb = FontBuilder(upem, isTTF=not cff)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({cp: glyph_name(cp) for cp in list(codepoints) + list(composites)})
    if cff:
        cs = {}
        for n in order:
            pen = T2CharStringPen(advance, None)
            _rect(pen, lsb, 0, lsb + stem, height)
            cs[n] = pen.getCharString()
        fb.setupCFF(f"{family}-{style}".replace(" ", ""), {"FullName": f"{family} {style}"}, cs, {})
    else:
        glyphs = {}
        for n in [".notdef"] + simple:
            pen = TTGlyphPen(None)
            _rect(pen, lsb, 0, lsb + stem, height)
            glyphs[n] = pen.glyph()
        for cp, base_cp in composites.items():
            pen = TTGlyphPen(glyphs)  # the pen checks that the component exists
            pen.addComponent(glyph_name(base_cp), (1, 0, 0, 1, 0, 0))
            glyphs[glyph_name(cp)] = pen.glyph()
        fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({n: (advance, lsb) for n in order})
    fb.setupHorizontalHeader(ascent=round(800 * k), descent=-round(200 * k))
    fb.setupNameTable({"familyName": family, "styleName": style})
    os2 = dict(sTypoAscender=round(800 * k), sTypoDescender=-round(200 * k), usWinAscent=round(800 * k),
               usWinDescent=round(200 * k), usWeightClass=weight, fsType=fs_type)
    if os2_version is not None:
        os2["version"] = os2_version
    fb.setupOS2(**os2)
    fb.setupPost()
    if kern:
        table = newTable("kern")
        table.version = 0
        st = KernTable_format_0(apple=False)
        st.version, st.coverage, st.format = 0, 1, 0
        st.kernTable = {(glyph_name(left), glyph_name(right)): v for (left, right), v in kern.items()}
        table.kernTables = [st]
        fb.font["kern"] = table
    if variable:
        fb.setupFvar([("wght", 100, 400, 900, "Weight")], [])
        # at wght=900 the stem is 100 units wider: the right-hand points and the right phantom point move
        deltas = [(0, 0), (100, 0), (100, 0), (0, 0), (0, 0), (100, 0), (0, 0), (0, 0)]
        fb.setupGvar({n: [TupleVariation({"wght": (0.0, 1.0, 1.0)}, deltas)] for n in order})
    fb.save(str(path))
    return Path(path)


def build_collection(path, font_paths) -> Path:
    coll = TTCollection()
    coll.fonts = [TTFont(str(p)) for p in font_paths]
    coll.save(str(path))
    return Path(path)


def fake_face(codepoints, *, path="fake.ttf", index=0, family="Fake", style="Regular", upem=1000,
              weight=400, outline="glyf", axes=(), embedding="installable", has_color=False) -> FontFace:
    """A FontFace with no file behind it, for planner/spec tests."""
    return FontFace(path=path, index=index, family=family, style=style, outline=outline,
                    is_collection=False, is_variable=bool(axes), axes=tuple(axes), weight_class=weight,
                    italic=False, upem=upem, glyph_count=len(codepoints) + 1,
                    codepoints=frozenset(codepoints), embedding=embedding, has_color=has_color, size=1, mtime=1.0)


def cps(text: str) -> set[int]:
    return {ord(c) for c in text}
