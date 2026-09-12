from PySide6.QtGui import QFont

from fontplayground.catalog.face import read_faces
from fontplayground.ui.preview import MISSING_COLOR, PreviewWidget, font_loader, make_font


def test_font_loader_maps_path_to_family(qapp, font_dir):
    assert font_loader().family_for(str(font_dir / "A.ttf"), preferred="Fixture A") == "Fixture A"
    assert font_loader().family_for(str(font_dir / "does-not-exist.ttf")) is None


def test_preview_marks_missing_characters(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    (a,) = read_faces(font_dir / "A.ttf")
    w.set_face(a)
    w.set_sample_text("ab 漢\nc")
    assert w.current_family() == "Fixture A"
    assert w.missing_characters() == ["漢"]
    html = w.browsers[0].toHtml()
    assert "漢" in html and "#ffb3b3" in html.lower()
    assert w.weight_slider.isHidden()


def test_preview_variable_shows_weight_slider(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    (v,) = read_faces(font_dir / "V.ttf")
    w.set_face(v)
    assert not w.weight_slider.isHidden()
    assert (w.weight_slider.minimum(), w.weight_slider.maximum()) == (100, 900)


def test_sample_changed_signal(qtbot):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.sampleChanged) as blocker:
        w.editor.setPlainText("hello")
    assert blocker.args == ["hello"] and w.sample_text() == "hello"


# ----- plan mode -----
def _fragments(doc):
    """(text, family, background colour name or None) for every fragment of every block, in order."""
    out = []
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            fmt = frag.charFormat()
            bg = fmt.background()
            colour = bg.color().name() if fmt.hasProperty(fmt.Property.BackgroundBrush) else None
            out.append((frag.text(), fmt.font().family(), colour))
            it += 1
        block = block.next()
    return out


def _plan(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    fonts = {f.key: (f.path, f.style, f.family, f.axes) for f in (a, b)}
    source = {ord(c): a.key for c in "abc"}
    source[ord("漢")] = b.key
    return a, b, fonts, source


def test_plan_mode_draws_each_run_in_its_font(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    a, b, fonts, source = _plan(font_dir)
    w.set_plan(fonts, source.get)
    w.set_sample_text("ab漢c")
    assert w.in_plan_mode() and w.current_family() == "Fixture A"
    assert w.missing_characters() == []
    assert w.weight_slider.isHidden()
    frags = _fragments(w.browsers[0].document())
    assert [(t, f) for t, f, _ in frags] == [("ab", "Fixture A"), ("漢", "Fixture B"), ("c", "Fixture A")]
    assert {f for _, f, _ in frags} == {"Fixture A", "Fixture B"}
    assert all(bg is None for _, _, bg in frags)
    fmt_font = w.browsers[0].document().begin().begin().fragment().charFormat().font()
    assert fmt_font.styleStrategy() & QFont.StyleStrategy.NoFontMerging


def test_plan_mode_marks_characters_nobody_draws(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    a, b, fonts, source = _plan(font_dir)
    w.set_plan(fonts, source.get)
    w.set_sample_text("ab漢c 한\nc")
    assert w.missing_characters() == ["한"]
    frags = _fragments(w.browsers[0].document())
    red = [t for t, _, bg in frags if bg == MISSING_COLOR]
    assert red == ["한"]
    assert [t for t, _, _ in frags] == ["ab", "漢", "c ", "한", "c"]  # the space is not red; new line = new block
    assert w.browsers[0].document().blockCount() == 2


def test_plan_mode_with_nothing_planned_shows_placeholder(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    w.set_plan({}, lambda cp: None)
    assert w.in_plan_mode() and w.current_family() is None
    assert w.missing_characters() == []
    assert "Select a font to preview" in w.browsers[0].toPlainText()


def test_plan_mode_uses_variable_font_default_weight(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    (v,) = read_faces(font_dir / "V.ttf")
    w.set_plan({v.key: (v.path, v.style, v.family, v.axes)}, lambda cp: v.key if chr(cp) in "ab" else None)
    w.set_sample_text("ab")
    assert w.weight_slider.isHidden()
    fmt_font = w.browsers[0].document().begin().begin().fragment().charFormat().font()
    assert fmt_font.family() == "Fixture V"
    assert fmt_font.variableAxisValue(QFont.Tag("wght")) == 400.0


def test_set_face_and_clear_leave_plan_mode(qtbot, font_dir):
    w = PreviewWidget(sizes=(12,))
    qtbot.addWidget(w)
    a, b, fonts, source = _plan(font_dir)
    w.set_plan(fonts, source.get)
    w.set_sample_text("ab漢c")
    w.set_face(a)
    assert not w.in_plan_mode() and w.current_family() == "Fixture A"
    assert w.missing_characters() == ["漢"]
    assert "#ffb3b3" in w.browsers[0].toHtml().lower()
    w.set_plan(fonts, source.get)
    assert w.in_plan_mode() and w.missing_characters() == []
    w.clear()
    assert not w.in_plan_mode() and w.current_family() is None and w.missing_characters() == []
    assert "Select a font to preview" in w.browsers[0].toPlainText()


def test_make_font_loads_and_configures(qapp, font_dir):
    (v,) = read_faces(font_dir / "V.ttf")
    font = make_font(v.path, v.style, v.family, 14, wght=700)
    assert font.family() == "Fixture V" and font.pointSize() == 14
    assert font.styleStrategy() & QFont.StyleStrategy.NoFontMerging
    assert font.variableAxisValue(QFont.Tag("wght")) == 700.0
    (b,) = read_faces(font_dir / "B.otf")
    font = make_font(b.path, b.style, b.family, 12)
    assert font.family() == "Fixture B" and font.styleName() == "Bold"
    assert make_font(b.path, None, b.family, 12).family() == "Fixture B"
