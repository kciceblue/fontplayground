from dataclasses import replace

from PySide6.QtGui import QFont

from fontplayground.catalog.face import read_faces
from fontplayground.ui import fonts
from fontplayground.ui.fonts import face_font, font_loader, make_font, mix_font, system_font
from fontplayground.ui.mix import MixFont


def test_font_loader_maps_path_to_family(qapp, font_dir):
    path = str(font_dir / "A.ttf")
    assert font_loader().family_for(path, preferred="Fixture A") == "Fixture A"
    assert font_loader().is_loaded(path)
    assert font_loader().family_for(str(font_dir / "does-not-exist.ttf")) is None


def test_make_font_loads_and_configures(qapp, font_dir):
    (v,) = read_faces(font_dir / "V.ttf")
    font = make_font(v.path, v.style, v.family, 14, wght=700)
    assert font.family() == "Fixture V" and font.pointSizeF() == 14
    assert font.styleStrategy() & QFont.StyleStrategy.NoFontMerging
    assert font.variableAxisValue(QFont.Tag("wght")) == 700.0
    (b,) = read_faces(font_dir / "B.otf")
    font = make_font(b.path, b.style, b.family, 12.5)
    assert font.family() == "Fixture B" and font.styleName() == "Bold" and font.pointSizeF() == 12.5
    assert make_font(b.path, None, b.family, 12).family() == "Fixture B"


def test_mix_font_applies_size_and_boldness(qapp, font_dir):
    (v,) = read_faces(font_dir / "V.ttf")
    (a,) = read_faces(font_dir / "A.ttf")
    assert mix_font(MixFont(v), 20).variableAxisValue(QFont.Tag("wght")) == 400.0   # the axis default
    font = mix_font(MixFont(v, 950, 0.5), 20)
    assert font.variableAxisValue(QFont.Tag("wght")) == 900.0 and font.pointSizeF() == 10   # clamped; scaled
    assert mix_font(MixFont(a, 700), 20).weight() == QFont.Weight.Bold                     # emboldened by Qt
    assert mix_font(MixFont(a, 450), 20).weight() == QFont.Weight.Normal                   # too close to bother
    assert mix_font(MixFont(a, None, 1.5), 20).pointSizeF() == 30


def test_face_font_prefers_an_installed_family_and_falls_back_to_the_file(qapp, font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    stranger = replace(a, family="No Such Family Anywhere", path=str(font_dir / "A.ttf"), index=7)
    assert system_font(stranger, 12) is None and fonts._SYSTEM[stranger.key] is False
    font = face_font(stranger, 12)
    assert font.family() == "Fixture A" and font.pointSizeF() == 12     # the file, loaded by make_font
    font_loader().family_for(a.path, a.family)
    assert system_font(a, 16).family() == "Fixture A"                   # known to Qt by name now
