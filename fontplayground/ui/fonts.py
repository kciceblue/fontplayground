"""QFonts for drawing: font files are loaded into Qt once, and every QFont draws its own glyphs only.

make_font/default_wght/FontLoader moved here from the old preview. mix_font draws a font of a Mix with its
boldness and size; face_font and system_font serve the picker, which draws hundreds of families and must not
load a file for each (an installed family is used by name when Qt confirms it is that family).
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo

from fontplayground.catalog.face import FontFace
from fontplayground.ui.mix import MixFont

SYNTHETIC_STEP = 100    # a static face asked for more than this above its own weight is drawn emboldened by Qt


class FontLoader:
    """Loads font files into Qt's font database once and maps path -> family name."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._families: dict[str, list[str]] = {}

    def family_for(self, path: str, preferred: str | None = None) -> str | None:
        if path not in self._ids:
            fid = QFontDatabase.addApplicationFont(path)
            self._ids[path] = fid
            self._families[path] = list(QFontDatabase.applicationFontFamilies(fid)) if fid >= 0 else []
        families = self._families[path]
        if not families:
            return None
        return preferred if preferred in families else families[0]

    def is_loaded(self, path: str) -> bool:
        """True once family_for has tried the file (so asking again costs nothing)."""
        return path in self._ids

    def unload(self, path: str) -> None:
        fid = self._ids.pop(path, None)
        self._families.pop(path, None)
        if fid is not None and fid >= 0:
            QFontDatabase.removeApplicationFont(fid)


_LOADER: FontLoader | None = None


def font_loader() -> FontLoader:
    global _LOADER
    if _LOADER is None:
        _LOADER = FontLoader()
    return _LOADER


def make_font(path: str, style: str | None, family: str | None, size: float, wght: float | None = None) -> QFont:
    """A QFont for one font file (loaded through font_loader) that never borrows glyphs from other fonts."""
    resolved = font_loader().family_for(path, family) or family or ""
    font = QFontDatabase.font(resolved, style, max(1, round(size))) if style else QFont(resolved)
    if font.family() != resolved:  # Qt did not know the style: keep at least the family
        font = QFont(resolved)
    font.setPointSizeF(float(size))
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    if wght is not None:
        font.setVariableAxis(QFont.Tag("wght"), float(wght))
    return font


def default_wght(axes) -> float | None:
    """The default weight of a variable font's weight axis, or None when it has none."""
    return next((float(a[2]) for a in axes if a[0] == "wght"), None)


def mix_font(mf: MixFont, size: float) -> QFont:
    """The font of one Mix entry at `size` × its scale, at its boldness.

    A variable font is drawn at the weight clamped to its axis (the axis default when the weight is "as is"). A
    static face asked to be clearly bolder than it is gets Qt's own emboldening — close to, not the same as, the
    build's synthetic bold.
    """
    face = mf.face
    axis = next((a for a in face.axes if a[0] == "wght"), None)
    if axis is not None:
        _tag, lo, default, hi = axis
        wght = float(default) if mf.weight is None else float(min(max(mf.weight, lo), hi))
        return make_font(face.path, face.style, face.family, size * mf.scale, wght)
    font = make_font(face.path, face.style, face.family, size * mf.scale)
    if mf.weight is not None and mf.weight > face.weight_class + SYNTHETIC_STEP:
        font.setStyleName("")          # a style name would override the weight in Qt's matching
        font.setWeight(QFont.Weight(mf.weight))
        font.setItalic(face.italic)
    return font


_SYSTEM: dict[tuple[str, int], bool] = {}     # face key -> the installed family draws it (checked once)


def system_font(face: FontFace, size: float) -> QFont | None:
    """The face as an installed family, without loading its file; None when Qt does not know it by that name."""
    known = _SYSTEM.get(face.key)
    if known is False:
        return None
    font = QFontDatabase.font(face.family, face.style, max(1, round(size)))
    font.setPointSizeF(float(size))
    font.setStyleStrategy(QFont.StyleStrategy.NoFontMerging)
    if known is None:
        known = QFontInfo(font).family().casefold() == face.family.casefold()
        _SYSTEM[face.key] = known
    return font if known else None


def face_font(face: FontFace, size: float) -> QFont:
    """The face at `size`: the installed family when Qt confirms it, else its file (loaded once)."""
    return system_font(face, size) or make_font(face.path, face.style, face.family, size)
