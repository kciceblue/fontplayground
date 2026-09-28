from PySide6.QtWidgets import QLabel, QWidget

from fontplayground.ui.widgets import Disclosure, ElidedLabel, elide_middle, set_flag


def test_elide_middle_keeps_head_and_tail():
    assert elide_middle("short", 10) == "short"
    assert elide_middle("x" * 10, 10) == "x" * 10
    shown = elide_middle("Save to ~\\Documents\\A very long font name-Regular.ttf", 21)
    assert len(shown) == 21 and shown.startswith("Save to ~\\") and shown.endswith("egular.ttf") and "…" in shown


def test_elided_label_elides_to_its_room_and_explains_in_the_tooltip(qtbot):
    label = ElidedLabel()
    qtbot.addWidget(label)
    label.show()                      # resize events (which re-check the tooltip) only reach a shown widget
    full = "Your text has Chinese and Japanese characters that the main font cannot draw"
    label.set_text(full)
    label.resize(label.sizeHint().width() + 10, 20)
    assert label.elided_text() == full and label.toolTip() == ""
    label.resize(60, 20)
    # Qt ends the cut with "…", or "..." when the label's font has no ellipsis glyph
    assert label.elided_text().endswith(("…", "...")) and label.elided_text() != full and label.toolTip() == full
    label.set_text("short", full_text="a much longer text")
    label.resize(400, 20)
    assert label.elided_text() == "short" and label.toolTip() == "a much longer text"


def test_disclosure_shows_and_hides_its_body(qtbot):
    body = QLabel("details")
    host = QWidget()
    qtbot.addWidget(host)
    body.setParent(host)
    toggle = Disclosure("Details", body, host)
    assert body.isHidden() and not toggle.isChecked()
    toggle.click()
    assert not body.isHidden()
    toggle.click()
    assert body.isHidden()


def test_set_flag_changes_the_property_only_when_needed(qtbot):
    label = QLabel()
    qtbot.addWidget(label)
    set_flag(label, "main", True)
    assert label.property("main") is True
    set_flag(label, "main", True)
    set_flag(label, "main", False)
    assert label.property("main") is False
