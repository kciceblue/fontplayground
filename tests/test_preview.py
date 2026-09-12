import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from fontplayground.catalog.face import read_faces
from fontplayground.ui.preview import (EDITOR_TOGGLE_TEXT, MISSING_COLOR, PLACEHOLDER_HTML, PreviewWidget, font_loader,
                                       make_font)


def _widget(qtbot, sizes=(12,), show=True) -> PreviewWidget:
    w = PreviewWidget(sizes=sizes)
    qtbot.addWidget(w)
    if show:
        w.show()
    return w


def test_font_loader_maps_path_to_family(qapp, font_dir):
    assert font_loader().family_for(str(font_dir / "A.ttf"), preferred="Fixture A") == "Fixture A"
    assert font_loader().family_for(str(font_dir / "does-not-exist.ttf")) is None


def test_preview_marks_missing_characters(qtbot, font_dir):
    w = _widget(qtbot)
    (a,) = read_faces(font_dir / "A.ttf")
    w.set_face(a)
    w.set_sample_text("ab 漢\nc")
    assert w.current_family() == "Fixture A"
    assert w.missing_characters() == ["漢"]
    html = w.browsers[0].toHtml()
    assert "漢" in html and "#ffb3b3" in html.lower()
    assert w.weight_slider.isHidden()


def test_preview_variable_shows_weight_slider(qtbot, font_dir):
    w = _widget(qtbot)
    (v,) = read_faces(font_dir / "V.ttf")
    w.set_face(v)
    assert not w.weight_slider.isHidden()
    assert (w.weight_slider.minimum(), w.weight_slider.maximum()) == (100, 900)


def test_sample_changed_signal(qtbot):
    w = _widget(qtbot, show=False)
    assert w.editor.isHidden()                       # the editor works while folded away
    with qtbot.waitSignal(w.sampleChanged) as blocker:
        w.editor.setPlainText("hello")
    assert blocker.args == ["hello"] and w.sample_text() == "hello"


# ----- S3: the sample editor is a disclosure -----
def test_editor_toggle_discloses_the_editor(qtbot):
    w = _widget(qtbot)
    toggle = w.editor_toggle
    assert toggle.text() == EDITOR_TOGGLE_TEXT == "Edit sample text"
    assert toggle.isCheckable() and not toggle.isChecked()
    assert toggle.arrowType() == Qt.ArrowType.RightArrow
    assert w.editor.isHidden() and not w.is_editor_visible()
    assert not w.browsers[0].isHidden()              # the size rows are there from the start
    toggle.click()
    assert w.is_editor_visible() and w.editor.isVisible() and toggle.isChecked()
    assert toggle.arrowType() == Qt.ArrowType.DownArrow
    toggle.click()
    assert not w.is_editor_visible() and w.editor.isHidden() and toggle.arrowType() == Qt.ArrowType.RightArrow
    w.set_editor_visible(True)                       # programmatic: the toggle follows
    assert w.is_editor_visible() and toggle.isChecked() and toggle.arrowType() == Qt.ArrowType.DownArrow
    w.set_editor_visible(False)
    assert not w.is_editor_visible() and not toggle.isChecked()
    # the toggle row comes before the editor, the weight row and the size rows
    layout = w.layout()
    order = [layout.itemAt(i) for i in range(layout.count())]
    assert order[0].layout() is not None and order[0].layout().itemAt(0).widget() is toggle
    assert order[1].widget() is w.editor
    assert order[2].layout().itemAt(0).widget() is w.weight_label
    assert order[3].widget() is w.scroll


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
    w = _widget(qtbot)
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
    w = _widget(qtbot)
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
    w = _widget(qtbot)
    w.set_plan({}, lambda cp: None)
    assert w.in_plan_mode() and w.current_family() is None
    assert w.missing_characters() == []
    assert "Select a font to preview" in w.browsers[0].toPlainText()


def test_plan_mode_uses_variable_font_default_weight(qtbot, font_dir):
    w = _widget(qtbot)
    (v,) = read_faces(font_dir / "V.ttf")
    w.set_plan({v.key: (v.path, v.style, v.family, v.axes)}, lambda cp: v.key if chr(cp) in "ab" else None)
    w.set_sample_text("ab")
    assert w.weight_slider.isHidden()
    fmt_font = w.browsers[0].document().begin().begin().fragment().charFormat().font()
    assert fmt_font.family() == "Fixture V"
    assert fmt_font.variableAxisValue(QFont.Tag("wght")) == 400.0


def test_set_face_and_clear_leave_plan_mode(qtbot, font_dir):
    w = _widget(qtbot)
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


# ----- S4: lazy, coalesced rendering -----
def _alternating_plan(font_dir):
    """Every 'a' from A, every 'b' from B: a sample of 'ab' * n alternates suppliers on every character."""
    a, b, fonts, _source = _plan(font_dir)
    return a, b, fonts, (lambda cp: a.key if cp == ord("a") else b.key if cp == ord("b") else None)


def test_hidden_widget_does_not_render_until_shown(qtbot, font_dir):
    w = _widget(qtbot, show=False)
    a, b, fonts, source = _plan(font_dir)
    assert w.browsers[0].document().isEmpty()        # not even the placeholder: nobody is looking
    w.set_plan(fonts, source.get)
    w.set_sample_text("ab漢")
    w.request_render()
    qtbot.wait(20)                                   # the coalescing timer fires… into a hidden widget
    assert w.browsers[0].document().isEmpty()
    assert w.missing_characters() == []              # answers never need a render
    w.show()
    frags = _fragments(w.browsers[0].document())     # shown: the owed render happened at once
    assert [(t, f) for t, f, _ in frags] == [("ab", "Fixture A"), ("漢", "Fixture B")]
    w.hide()
    w.set_sample_text("漢b")                         # hidden again: skipped again
    assert [t for t, _, _ in _fragments(w.browsers[0].document())] == ["ab", "漢"]
    w.show()
    assert [t for t, _, _ in _fragments(w.browsers[0].document())] == ["漢", "b"]


def test_a_keystroke_renders_once(qtbot, monkeypatch, font_dir):
    calls = []
    original = PreviewWidget._fill_plan_document
    monkeypatch.setattr(PreviewWidget, "_fill_plan_document",
                        lambda self, browser, size: (calls.append(size), original(self, browser, size)))
    w = _widget(qtbot, sizes=(12, 24))
    a, b, fonts, source = _plan(font_dir)
    w.set_plan(fonts, source.get)
    w.set_sample_text("ab")
    qtbot.wait(20)                                   # let show/resize requests settle
    calls.clear()
    w.editor.setPlainText("abc")                     # what typing does: textChanged
    w.request_render()
    w.request_render()
    w.size_spins[0].setValue(13)
    assert calls == []                               # nothing yet: the timer coalesces
    qtbot.waitUntil(lambda: len(calls) >= 2, timeout=2000)
    qtbot.wait(20)
    assert calls == [13, 24]                         # one render: each size row once
    assert [t for t, _, _ in _fragments(w.browsers[0].document())] == ["abc"]


def test_large_alternating_sample_renders_fast(qtbot, font_dir):
    w = _widget(qtbot, sizes=(12, 24, 48))
    a, b, fonts, source_of = _alternating_plan(font_dir)
    w.set_plan(fonts, source_of)
    sample = "ab" * 1500
    assert len(sample) == 3000
    started = time.perf_counter()
    w.set_sample_text(sample)                        # renders at once: the widget is visible
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"3,000 alternating characters took {elapsed:.2f}s"
    frags = _fragments(w.browsers[0].document())
    assert len(frags) == 3000 and {f for _, f, _ in frags} == {"Fixture A", "Fixture B"}
    assert "".join(t for t, _, _ in frags) == sample


def test_placeholder_arrives_with_the_first_show(qtbot):
    w = _widget(qtbot, show=False)
    assert w.browsers[0].document().isEmpty()
    w.show()
    assert "Select a font to preview" in w.browsers[0].toPlainText()
    assert PLACEHOLDER_HTML.startswith("<span")


# ----- S5: invisible characters are never missing -----
def test_invisible_characters_are_never_missing_in_single_font_mode(qtbot, font_dir):
    w = _widget(qtbot)
    (a,) = read_faces(font_dir / "A.ttf")
    w.set_face(a)
    w.set_sample_text("a‍b️ c­‎\t漢")   # ZWJ, VS16, soft hyphen, LRM, tab
    assert w.missing_characters() == ["漢"]
    html = w.browsers[0].toHtml().lower()
    assert html.count("#ffb3b3") == 1 and "漢" in html


def test_invisible_characters_join_their_neighbours_in_plan_mode(qtbot, font_dir):
    w = _widget(qtbot)
    a, b, fonts, source = _plan(font_dir)
    w.set_plan(fonts, source.get)
    w.set_sample_text("a‍漢️​b 한‍")     # ZWJ, VS16, ZWSP, ZWJ
    assert w.missing_characters() == ["한"]
    frags = _fragments(w.browsers[0].document())
    assert [t for t, _, bg in frags if bg == MISSING_COLOR] == ["한"]   # the joiner after 한 is not red
    assert [(t, f) for t, f, _ in frags] == [("a‍", "Fixture A"), ("漢️​", "Fixture B"),
                                             ("b ", "Fixture A"), ("한", "Fixture A"), ("‍", "Fixture A")]
