from fontplayground.catalog.face import read_faces
from fontplayground.ui.preview import PreviewWidget, font_loader


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
