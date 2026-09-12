import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest

from fontplayground.catalog.face import read_faces
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.tray import MAX_HEIGHT, MIN_HEIGHT, Chip, MaterialsTray, chip_label


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    (c,) = read_faces(font_dir / "C.ttf")
    return a, b, c


@pytest.fixture
def model(qapp):
    return ForgeModel()


@pytest.fixture
def tray(qtbot, model):
    t = MaterialsTray(model)
    qtbot.addWidget(t)
    t.show()
    return t


def test_chips_follow_the_model(tray, model, faces):
    a, b, c = faces
    assert tray.chip_labels() == [] and tray.hint_label.text() == "Pick a font to begin."
    assert tray.recap_label.text() == "0 fonts · 0 characters"
    model.add(a)
    assert tray.chip_labels() == ["Main · Fixture A Regular"]
    assert tray.recap_label.text().startswith("1 font ·")
    model.add(b)
    model.add(c)
    assert tray.chip_labels() == ["Main · Fixture A Regular", "2 · Fixture B Bold", "3 · Fixture C Regular"]
    assert chip_label(0, "X") == "Main · X" and chip_label(4, "X") == "5 · X"
    main, second = tray.chip_widget(0), tray.chip_widget(1)
    assert isinstance(main, Chip) and main.text() == "Main · Fixture A Regular" and main.key == a.key
    assert main.property("main") is True and second.property("main") is False
    assert main.toolTip() == "Fixture A Regular\nCovers: Latin"
    assert second.toolTip() == "Fixture B Bold\nCovers: Latin, Han, CJK symbols & fullwidth"
    assert tray.chip_widget(2).toolTip() == "Fixture C Regular\nCovers: Latin, Greek, Punctuation & symbols"
    model.remove(b.key)
    assert tray.chip_labels() == ["Main · Fixture A Regular", "2 · Fixture C Regular"]


def test_set_order_relabels_the_chips(tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.set_order([b.key, a.key])
    assert tray.chip_labels() == ["Main · Fixture B Bold", "2 · Fixture A Regular"]
    assert tray.chip_widget(0).property("main") is True and tray.chip_widget(1).property("main") is False
    assert tray.list.keys() == [b.key, a.key]


def test_drag_reorder_reaches_the_model_through_rows_moved(qtbot, tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.add(c)
    assert tray.list.model().moveRow(QModelIndex(), 2, QModelIndex(), 0)  # what an internal drop does
    qtbot.waitUntil(lambda: model.keys() == [c.key, a.key, b.key], timeout=2000)
    assert tray.chip_labels() == ["Main · Fixture C Regular", "2 · Fixture A Regular", "3 · Fixture B Bold"]
    assert all(isinstance(tray.chip_widget(i), Chip) for i in range(3))  # widgets survive the rebuild


def test_drop_that_changes_nothing_still_restores_the_chip_widgets(qtbot, tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    item = tray.list.takeItem(1)         # a Static-movement drop takes the item and puts it back...
    tray.list.insertItem(1, item)        # ...which loses its widget
    assert tray.list.itemWidget(tray.list.item(1)) is None
    tray.list.orderChanged.emit()
    qtbot.waitUntil(lambda: tray.list.itemWidget(tray.list.item(1)) is not None, timeout=2000)
    assert model.keys() == [a.key, b.key] and tray.chip_labels() == ["Main · Fixture A Regular", "2 · Fixture B Bold"]


def test_close_button_and_delete_key_remove(qtbot, tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.add(c)
    tray.chip_widget(1).close_button.click()
    assert model.keys() == [a.key, c.key]
    tray.list.setCurrentRow(1)
    QTest.keyClick(tray.list, Qt.Key.Key_Delete)
    assert model.keys() == [a.key]
    tray.list.setCurrentRow(-1)
    QTest.keyClick(tray.list, Qt.Key.Key_Delete)  # no current chip: nothing happens
    assert model.keys() == [a.key]
    tray.list.setCurrentRow(0)
    QTest.keyClick(tray.list, Qt.Key.Key_Backspace)
    assert model.keys() == [] and tray.chip_labels() == []


def test_hint_shows_missing_chars_with_suggestion_buttons(qtbot, tray, model, faces):
    a, b, c = faces
    model.set_catalog({f.key: f for f in (a, b, c)})
    model.set_sample_text("ab →")
    model.add(a)
    assert tray.hint_label.text() == "Your sample still needs: →"
    assert "#b91c1c" in tray.hint_label.styleSheet()
    buttons = tray.suggestion_buttons()
    assert [x.text() for x in buttons] == ["Add Fixture C"]
    assert buttons[0].toolTip() == "Add Fixture C Regular to your materials"
    buttons[0].click()
    assert model.keys() == [a.key, c.key]
    assert tray.hint_label.text() == "Your sample is fully covered."
    assert "#15803d" in tray.hint_label.styleSheet() and tray.suggestion_buttons() == []

    model.set_sample_text("ab →漢")  # the sample changed: the hint follows without a materials change
    assert tray.hint_label.text() == "Your sample still needs: 漢"
    assert [x.text() for x in tray.suggestion_buttons()] == ["Add Fixture B"]
    model.remove(a.key)
    model.remove(c.key)
    assert tray.hint_label.text() == "Pick a font to begin." and tray.suggestion_buttons() == []


def test_hint_caps_the_characters_it_lists(tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.set_sample_text("".join(chr(0x3041 + i) for i in range(25)))
    text = tray.hint_label.text()
    assert text.startswith("Your sample still needs: ぁ") and text.endswith(" …")
    assert len(text.split(": ")[1].split()) == 21
    assert len(tray.hint_label.toolTip().split()) == 25


def test_recap_counts_fonts_and_planned_characters(qtbot, tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    with qtbot.waitSignal(model.planChanged, timeout=2000):
        pass
    assert tray.recap_label.text() == "2 fonts · 7 characters"
    model.remove(b.key)
    model.recompute_plan_now()
    assert tray.recap_label.text() == "1 font · 5 characters"


def test_primary_back_and_add_controls(qtbot, tray):
    tray.set_primary("Next: Check ›", False, "Add a font first")
    assert tray.primary_button.text() == "Next: Check ›" and not tray.primary_button.isEnabled()
    assert tray.primary_button.toolTip() == "Add a font first"
    tray.set_primary("Forge ›", True)
    assert tray.primary_button.isEnabled() and tray.primary_button.toolTip() == ""
    with qtbot.waitSignal(tray.primaryClicked):
        tray.primary_button.click()
    tray.set_back_visible(False)
    assert tray.back_button.isHidden()
    tray.set_back_visible(True)
    assert not tray.back_button.isHidden()
    with qtbot.waitSignal(tray.backClicked):
        tray.back_button.click()
    with qtbot.waitSignal(tray.addClicked):
        tray.add_button.click()
    assert tray.add_button.text() == "+ add"


def test_tray_height_stays_compact(tray, model, faces):
    a, b, c = faces
    for f in faces:
        model.add(f)
    assert (tray.minimumHeight(), tray.maximumHeight()) == (MIN_HEIGHT, MAX_HEIGHT) == (64, 84)
    assert MIN_HEIGHT <= tray.height() <= MAX_HEIGHT
