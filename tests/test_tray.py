import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu, QSizePolicy, QToolButton

from fontplayground.catalog.face import read_faces
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.tray import (MAX_HEIGHT, MAX_PRIMARY_CHARS, MIN_HEIGHT, PRIMARY_MIN_WIDTH, SUGGESTION_MIN_WIDTHS, Chip,
                                    MaterialsTray, chip_label, elide_middle)
from fontplayground.ui.theme import DARK, LIGHT
from tests.fixtures import cps, fake_face

WIDE = 1600   # room for every label at the offscreen platform's (wide) font metrics
LONG_PRIMARY = "Save to C:\\Users\\somebody\\Documents\\fonts\\Forged Family SemiBold.ttf ▾"   # 70 characters


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
    t.resize(WIDE, 72)
    t.show()
    return t


def _visible(buttons):
    return [not b.isHidden() for b in buttons]


def _crowded(model, missing_count=20, family="Some Very Long Suggested Family Name {i}"):
    """One material, a sample missing `missing_count` characters, and three suggestions (named `family`) in the catalog."""
    missing = "".join(chr(0x3041 + i) for i in range(missing_count))
    a = fake_face(cps("abc"), path="a.ttf", family="Fixture A")
    suggested = [fake_face(cps(missing[i::3]), path=f"s{i}.ttf", family=family.format(i=i)) for i in range(3)]
    model.set_catalog({f.key: f for f in [a] + suggested})
    model.add(a)
    model.set_sample_text("abc " + missing)
    return missing


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
    assert tray.hint_label.toolTip() == ""            # nothing hidden: no tooltip
    assert LIGHT.danger in tray.hint_label.styleSheet()
    buttons = tray.suggestion_buttons()
    assert [x.text() for x in buttons] == ["Add Fixture C"]
    assert buttons[0].toolTip() == "Add Fixture C Regular to your materials"
    buttons[0].click()
    assert model.keys() == [a.key, c.key]
    assert tray.hint_label.text() == "Your sample is fully covered."
    assert LIGHT.ok in tray.hint_label.styleSheet() and tray.suggestion_buttons() == []
    assert tray.suggestions_box.isHidden()

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
    tooltip = tray.hint_label.toolTip()                 # the tooltip tells the whole story
    assert tooltip.startswith("Your sample still needs: ぁ") and len(tooltip.split(": ")[1].split()) == 25
    assert tray.hint_label.full_text() == tooltip


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


# ----- S1: the tray never dictates the window width -----
def test_elide_middle_keeps_head_and_tail():
    assert elide_middle("short") == "short"
    assert elide_middle("x" * MAX_PRIMARY_CHARS) == "x" * MAX_PRIMARY_CHARS
    assert len(LONG_PRIMARY) == 70
    shown = elide_middle(LONG_PRIMARY)
    assert len(shown) == MAX_PRIMARY_CHARS and "…" in shown
    assert shown.startswith("Save to C:\\Users\\") and shown.endswith("SemiBold.ttf ▾")
    assert elide_middle("abcdefgh", 5) == "ab…gh"


def test_tray_minimum_width_is_bounded_whatever_the_texts(qtbot, tray, model):
    missing = _crowded(model, missing_count=20)
    assert len(model.missing_sample_chars()) == 20
    buttons = tray.suggestion_buttons()
    assert len(buttons) == 3 and all(b.text().startswith("Add Some Very Long") for b in buttons)
    tray.set_back_visible(True)
    tray.set_primary(LONG_PRIMARY, True)
    assert tray.minimumSizeHint().width() <= 900
    # the mechanisms behind the number
    for label in (tray.hint_label, tray.recap_label):
        assert label.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
        assert label.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Preferred
    assert tray.suggestions_box.minimumWidth() == 0
    assert len(tray.primary_button.text()) == MAX_PRIMARY_CHARS
    assert tray.hint_label.full_text() == "Your sample still needs: " + " ".join(missing)
    # even squeezed to the bone nothing overflows: every part fits inside the tray
    tray.resize(tray.minimumSizeHint().width(), 72)
    qtbot.waitUntil(lambda: tray.width() == tray.minimumSizeHint().width(), timeout=2000)
    assert tray.width() <= 900
    for widget in (tray.list, tray.add_button, tray.recap_label, tray.hint_label, tray.suggestions_box,
                   tray.back_button, tray.primary_button):
        assert widget.geometry().right() <= tray.width()
    primary = tray.primary_button
    assert primary.width() >= primary.minimumSizeHint().width() == min(primary.sizeHint().width(), PRIMARY_MIN_WIDTH)


def test_primary_label_is_capped_with_the_full_text_in_the_tooltip(tray):
    long = "Save to " + "C:\\a very deep folder\\" * 3 + "Family.ttf ▾"
    assert len(long) > MAX_PRIMARY_CHARS
    tray.set_primary(long, True)
    shown = tray.primary_button.text()
    assert len(shown) == MAX_PRIMARY_CHARS and shown == elide_middle(long)
    assert shown.startswith("Save to C:\\") and shown.endswith("Family.ttf ▾")
    assert tray.primary_button.toolTip() == long
    tray.set_primary(long, False, "Pick a folder first")           # both the full text and the explanation
    assert tray.primary_button.toolTip() == long + "\nPick a folder first"
    tray.set_primary("Next: Check ›", True)                          # short: as given, no tooltip
    assert tray.primary_button.text() == "Next: Check ›" and tray.primary_button.toolTip() == ""


def test_hint_elides_to_the_room_it_gets(qtbot, tray, model, faces):
    a, b, c = faces
    model.add(a)
    model.set_sample_text("".join(chr(0x3041 + i) for i in range(20)))   # no catalog: a long hint, no buttons
    tray.set_primary("Next ›", True)
    hint = tray.hint_label
    full = hint.full_text()
    assert hint.text() == full and hint.elided_text() == full and hint.toolTip() == ""
    natural = hint.sizeHint().width()
    assert hint.width() == natural == hint.maximumWidth()                   # its natural width, no more
    # narrow the tray, half a hint at a time, until the hint no longer gets all it needs (never to zero)
    width = tray.width()
    while hint.width() >= natural and width > tray.minimumSizeHint().width():
        width = max(width - natural // 2, tray.minimumSizeHint().width())
        tray.resize(width, 72)
        qtbot.waitUntil(lambda: tray.width() == width, timeout=2000)
    assert 0 < hint.width() < natural
    assert hint.text() == full                                              # the logical text never changes…
    painted = hint.elided_text()
    assert painted != full and painted.endswith("…") and full.startswith(painted[:-1])   # …the painted one does
    assert hint.toolTip() == full
    tray.resize(WIDE, 72)
    qtbot.waitUntil(lambda: hint.elided_text() == full, timeout=2000)
    assert hint.toolTip() == ""
    # a label with a shortened text tells the whole story in its tooltip even when nothing is elided
    model.set_sample_text("".join(chr(0x3041 + i) for i in range(25)))
    assert hint.elided_text() == hint.text() != hint.full_text() and hint.toolTip() == hint.full_text()


def test_suggestions_hide_as_the_tray_narrows(qtbot, tray, model):
    _crowded(model, missing_count=20)
    tray.set_primary("Next ›", True)
    buttons = tray.suggestion_buttons()
    assert len(buttons) == 3 and SUGGESTION_MIN_WIDTHS == (0, 860, 1000)
    assert _visible(buttons) == [True, True, True]
    tray.resize(1000, 72)
    qtbot.waitUntil(lambda: tray.width() == 1000, timeout=2000)
    assert _visible(buttons) == [True, True, True]
    tray.resize(950, 72)
    qtbot.waitUntil(lambda: tray.width() == 950, timeout=2000)
    assert _visible(buttons) == [True, True, False]          # the third goes first…
    tray.resize(800, 72)
    qtbot.waitUntil(lambda: tray.width() == 800, timeout=2000)
    assert _visible(buttons) == [True, False, False]         # …then the second; the first always stays
    assert not tray.suggestions_box.isHidden()
    tray.resize(WIDE, 72)
    qtbot.waitUntil(lambda: tray.width() == WIDE, timeout=2000)
    assert _visible(buttons) == [True, True, True]
    model.set_sample_text("abc")                              # nothing missing: the box itself goes
    assert tray.suggestion_buttons() == [] and tray.suggestions_box.isHidden()


def test_visible_suggestion_buttons_are_never_clipped(qtbot, tray, model):
    """A button the tray decides to show is shown whole: the box is served first, the labels elide around it."""
    _crowded(model, missing_count=20, family="Fam {i}")       # short names: three buttons fit at every width below
    tray.set_primary("Next ›", True)
    buttons = tray.suggestion_buttons()
    hint, recap = tray.hint_label, tray.recap_label
    assert tray.suggestions_box.minimumSizeHint().width() == 0   # …yet the box never asks the window for room
    for width, expected in ((1100, [True, True, True]), (950, [True, True, False]), (800, [True, False, False])):
        tray.resize(width, 72)
        qtbot.waitUntil(lambda: tray.width() == width, timeout=2000)
        assert _visible(buttons) == expected
        shown = [b for b in buttons if not b.isHidden()]
        assert [b.width() for b in shown] == [b.sizeHint().width() for b in shown], f"clipped at {width}"
        natural = sum(b.sizeHint().width() for b in shown) + tray.suggestions_layout.spacing() * (len(shown) - 1)
        assert tray.suggestions_box.width() == natural
        # the labels take what is left (all they need, or less: with the offscreen platform's wide default
        # font they elide here; once earlier tests registered the tiny fixture fonts everything fits)
        assert 0 < recap.width() <= recap.sizeHint().width() and 0 < hint.width() <= hint.sizeHint().width()
        assert hint.toolTip() == ("" if hint.elided_text() == hint.full_text() else hint.full_text())


# ----- S2: the primary button's menu -----
def test_primary_menu_button_appears_with_a_menu(qtbot, tray):
    button = tray.primary_menu_button
    assert isinstance(button, QToolButton) and button.objectName() == "primaryMenu"
    assert button.isHidden() and button.menu() is None
    assert tray.primary_button.property("attached") in (None, False)
    menu = QMenu(tray)
    action = menu.addAction("Choose location…")
    tray.set_primary_menu(menu)
    assert not button.isHidden() and button.menu() is menu and button.text() == "▾"
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup
    assert button.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert tray.primary_button.property("attached") is True
    assert menu.actions() == [action]
    # glued: same row, directly to the right of the primary button, same height
    assert button.geometry().left() == tray.primary_button.geometry().right() + 1
    assert button.height() == tray.primary_button.height()
    tray.set_primary_menu(None)
    assert button.isHidden() and button.menu() is None
    assert tray.primary_button.property("attached") is False


def test_apply_theme_rerenders_sheet_and_hint(tray, model, faces):
    assert LIGHT.accent in tray.styleSheet() and LIGHT.text_secondary in tray.hint_label.styleSheet()
    tray.apply_theme(DARK)
    assert DARK.accent in tray.styleSheet() and LIGHT.accent not in tray.styleSheet()
    assert DARK.text_secondary in tray.hint_label.styleSheet()   # "Pick a font to begin." keeps its tone
    a, b, c = faces
    model.set_catalog({f.key: f for f in (a, b, c)})
    model.set_sample_text("ab →")
    model.add(a)
    assert DARK.danger in tray.hint_label.styleSheet()
    dark = MaterialsTray(model, theme=DARK)
    assert DARK.surface in dark.styleSheet()
