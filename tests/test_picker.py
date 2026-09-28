"""FontPicker: the list the left column shows while the user chooses a font (spec §2 "Picker")."""
import pytest
from PySide6.QtCore import Qt

from fontplayground.catalog.face import FontFace, read_faces
from fontplayground.catalog.scanner import ScanResult
from fontplayground.ui import fonts, smart
from fontplayground.ui.languages import LANGUAGES
from fontplayground.ui.picker import (FACE_ROLE, HEADER_ROLE, IN_RECIPE_TAG, NATIVE_ROLE, STYLE, TAG_ROLE,
                                      FontPicker)
from fontplayground.ui.requests import PickRequest
from fontplayground.ui.theme import DARK, LIGHT
from tests.fixtures import build_font, cps, fake_face

MARKERS = "们这说国门来"                                              # chinese_s markers
LATIN_CPS = set(range(0x21, 0x7F)) | set(range(0xC0, 0xC6))          # 100 Latin characters
ZETA_NAMES = {1: [(3, 1, 0x409, "Picker Zeta"), (3, 1, 0x804, "测试黑体")]}


@pytest.fixture(scope="module")
def catalog(tmp_path_factory) -> dict[str, FontFace]:
    """S: 2,600 Han + the markers; H: 2,600 Han without them; L/LB: a Latin family of two faces; Z: Latin with a
    Chinese native name; X: a bitmap-only (unsupported) face with no file."""
    d = tmp_path_factory.mktemp("picker")
    build_font(d / "S.ttf", "Picker Simplified", "Regular", set(range(0x4E00, 0x4E00 + 2600)) | cps(MARKERS + "Aa1"))
    build_font(d / "H.ttf", "Picker Plain Han", "Regular", set(range(0x5600, 0x5600 + 2600)))
    build_font(d / "L.ttf", "Picker Latin", "Regular", LATIN_CPS)
    build_font(d / "LB.ttf", "Picker Latin", "Bold", LATIN_CPS, weight=700)
    build_font(d / "Z.ttf", "Picker Zeta", "Regular", LATIN_CPS, name_records=ZETA_NAMES)
    faces = {p.stem: read_faces(p)[0] for p in sorted(d.glob("*.ttf"))}
    faces["X"] = fake_face(LATIN_CPS, path=str(d / "X.fon"), family="Picker Bitmap", outline="none")
    return faces


def filled(qtbot, faces) -> FontPicker:
    picker = FontPicker()
    qtbot.addWidget(picker)
    picker.begin_scan()
    for face in faces:
        picker.add_face(face)
    picker.end_scan(ScanResult(faces=list(faces)))
    return picker


@pytest.fixture
def picker(qtbot, catalog) -> FontPicker:
    return filled(qtbot, catalog.values())


def choose_language(picker: FontPicker, lang_id: str) -> None:
    picker.language_combo.setCurrentIndex(picker.language_combo.findData(lang_id))


def rows_data(picker: FontPicker, role) -> dict[str, object]:
    model = picker.view.model()
    return {model.index(i, 0).data(): model.index(i, 0).data(role) for i in range(model.rowCount())}


def current_row(picker: FontPicker) -> int:
    return picker.view.currentIndex().row()


# ----- listing ------------------------------------------------------------------------------------
def test_combo_lists_every_language(picker):
    combo = picker.language_combo
    assert [combo.itemText(i) for i in range(combo.count())] == [lang.label for lang in LANGUAGES]
    assert [combo.itemData(i) for i in range(combo.count())] == [lang.id for lang in LANGUAGES]


def test_language_filter_lists_the_families_that_draw_it_well(picker, catalog):
    picker.open(PickRequest("chinese_s"), None, set(), [])
    assert picker.language() == "chinese_s"
    assert picker.visible_families() == ["Picker Simplified"]          # Plain Han lacks the markers
    assert picker.search.placeholderText() == "Search 1 font — English or native name"
    choose_language(picker, "any")
    assert picker.language() == "any"
    assert picker.visible_families() == ["Picker Latin", "Picker Plain Han", "Picker Simplified", "Picker Zeta"]
    assert picker.search.placeholderText() == "Search 4 fonts — English or native name"
    choose_language(picker, "latin")
    assert picker.visible_families() == ["Picker Latin", "Picker Zeta"]
    choose_language(picker, "korean")
    assert picker.visible_families() == [] and picker.row_texts() == []
    assert picker.status_label.text() == "None of your fonts draw Korean well."
    # the unsupported face is never listed but stays in the catalog
    assert catalog["X"].key in picker.faces_by_key() and len(picker.faces_by_key()) == 6


def test_search_matches_the_family_and_native_names_ignoring_case(picker, catalog):
    picker.open(PickRequest("any"), None, set(), [])
    picker.search.setText("ZETA")
    assert picker.visible_families() == ["Picker Zeta"]
    picker.search.setText("测试")
    assert picker.visible_families() == ["Picker Zeta"]
    assert rows_data(picker, NATIVE_ROLE)["Picker Zeta"] == "测试黑体"
    picker.search.setText("plain")
    assert picker.visible_families() == ["Picker Plain Han"]
    picker.search.setText("nothing like it")
    assert picker.row_texts() == [] and picker.current_face() is None
    assert picker.status_label.text() == "No fonts match “nothing like it”."
    assert not picker.use_button.isEnabled()
    picker.search.clear()
    assert len(picker.visible_families()) == 4 and picker.status_label.text() == "6 fonts"


def test_sections_and_counts(picker, catalog):
    picker.open(PickRequest("chinese_s"), catalog["L"], {catalog["L"].key}, [])
    assert picker.row_texts() == ["ALL CHINESE FONTS · 1", "Picker Simplified"]
    picker.open(PickRequest("latin"), None, set(), [])
    assert picker.row_texts() == ["ALL LATIN FONTS · 2", "Picker Latin", "Picker Zeta"]
    picker.open(PickRequest("any"), None, set(), [])
    assert picker.row_texts()[0] == "ALL FONTS · 4"
    picker.search.setText("han")
    assert picker.row_texts() == ["ALL FONTS · 1", "Picker Plain Han"]
    # header rows are neither selectable nor enabled
    header = picker.view.model().index(0, 0)
    assert header.data(HEADER_ROLE) is True and header.data(FACE_ROLE) is None
    assert not header.flags() & Qt.ItemFlag.ItemIsSelectable and not header.flags() & Qt.ItemFlag.ItemIsEnabled


def test_suggested_section_only_with_suggestions_that_pass_the_filters(picker, catalog):
    picker.open(PickRequest("latin"), None, set(), [catalog["Z"]])
    assert picker.row_texts() == ["SUGGESTED FOR YOUR TEXT", "Picker Zeta", "ALL LATIN FONTS · 2", "Picker Latin",
                                  "Picker Zeta"]
    assert picker.visible_families() == ["Picker Latin", "Picker Zeta"]
    assert current_row(picker) == 1 and picker.current_face() == catalog["Z"]   # the first selectable row
    picker.search.setText("latin")                                              # the suggestion does not match
    assert picker.row_texts() == ["ALL LATIN FONTS · 1", "Picker Latin"]
    picker.open(PickRequest("latin"), None, set(), [catalog["S"]])             # does not draw Latin well
    assert picker.row_texts()[0] == "ALL LATIN FONTS · 2"


def test_in_your_font_tag_marks_families_of_the_recipe(picker, catalog):
    picker.open(PickRequest("latin"), None, {catalog["LB"].key}, [])
    assert rows_data(picker, TAG_ROLE) == {"ALL LATIN FONTS · 2": "", "Picker Latin": IN_RECIPE_TAG,
                                           "Picker Zeta": ""}
    assert IN_RECIPE_TAG == "in your font"


def test_titles_for_main_add_and_replace(picker, catalog):
    picker.open(PickRequest("latin"), None, set(), [])
    assert picker.title_label.text() == "Choose your main font"
    main = catalog["L"]
    picker.open(PickRequest("chinese_s"), main, {main.key}, [])
    assert picker.title_label.text() == "Choose a font for Chinese"
    picker.open(PickRequest("any"), main, {main.key}, [])
    assert picker.title_label.text() == "Choose a font"
    picker.open(PickRequest("latin", replace_key=catalog["Z"].key), main, {main.key, catalog["Z"].key}, [])
    assert picker.title_label.text() == "Replace Picker Zeta"
    assert picker.current_face() == catalog["Z"]           # the replaced font's family is the current row
    assert picker.language() == "latin" and picker.search.text() == ""


def test_open_clears_the_search_and_sets_the_language(picker, catalog):
    picker.open(PickRequest("any"), None, set(), [])
    picker.search.setText("zeta")
    picker.open(PickRequest("chinese_s"), catalog["L"], set(), [])
    assert picker.search.text() == "" and picker.language() == "chinese_s"
    assert picker.current_face() == catalog["S"]


# ----- keyboard and choosing ----------------------------------------------------------------------
def test_arrows_typed_in_the_search_move_the_current_row_skipping_headers(qtbot, picker, catalog):
    picker.resize(420, 700)
    picker.show()
    picker.open(PickRequest("latin"), None, set(), [catalog["Z"]])
    # rows: SUGGESTED, Zeta, ALL LATIN FONTS, Latin, Zeta
    assert current_row(picker) == 1
    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert current_row(picker) == 3 and picker.current_face() == catalog["L"]
    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert current_row(picker) == 4
    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert current_row(picker) == 4                        # the last row stays put
    qtbot.keyClick(picker.search, Qt.Key.Key_Up)
    qtbot.keyClick(picker.search, Qt.Key.Key_Up)
    assert current_row(picker) == 1
    qtbot.keyClick(picker.search, Qt.Key.Key_Up)
    assert current_row(picker) == 1
    qtbot.keyClick(picker.search, Qt.Key.Key_PageDown)
    assert current_row(picker) == 4
    qtbot.keyClick(picker.search, Qt.Key.Key_PageUp)
    assert current_row(picker) == 1
    # the list itself skips headers too, and typing still types
    qtbot.keyClick(picker.view, Qt.Key.Key_Down)
    assert current_row(picker) == 3
    qtbot.keyClicks(picker.search, "zet")
    assert picker.search.text() == "zet"


def test_enter_uses_the_families_default_face(qtbot, picker, catalog):
    latin = [catalog["L"], catalog["LB"]]
    picker.open(PickRequest("latin"), None, set(), [])
    with qtbot.waitSignal(picker.chosen, timeout=1000) as blocker:
        qtbot.keyClick(picker.search, Qt.Key.Key_Return)
    assert blocker.args == [smart.default_face(latin, None)] == [catalog["L"]]
    bold_main = fake_face(LATIN_CPS, path="main-bold.ttf", family="Main", weight=700)
    picker.open(PickRequest("latin"), bold_main, {bold_main.key}, [])
    with qtbot.waitSignal(picker.chosen, timeout=1000) as blocker:
        qtbot.keyClick(picker.search, Qt.Key.Key_Enter)
    assert blocker.args == [smart.default_face(latin, bold_main)] == [catalog["LB"]]


def test_enter_in_the_list_and_double_click_use_the_row(qtbot, picker, catalog):
    picker.open(PickRequest("latin"), None, set(), [])
    with qtbot.waitSignal(picker.chosen, timeout=1000) as blocker:
        qtbot.keyClick(picker.view, Qt.Key.Key_Return)
    assert blocker.args == [catalog["L"]]
    model = picker.view.model()
    with qtbot.waitSignal(picker.chosen, timeout=1000) as blocker:
        picker.view.doubleClicked.emit(model.index(2, 0))
    assert blocker.args == [catalog["Z"]] and picker.current_face() == catalog["Z"]
    with qtbot.assertNotEmitted(picker.chosen):
        picker.view.doubleClicked.emit(model.index(0, 0))   # a header


def test_escape_back_and_cancel_emit_cancelled(qtbot, picker):
    picker.open(PickRequest("latin"), None, set(), [])
    with qtbot.waitSignal(picker.cancelled, timeout=1000):
        qtbot.keyClick(picker.search, Qt.Key.Key_Escape)
    with qtbot.waitSignal(picker.cancelled, timeout=1000):
        qtbot.keyClick(picker.view, Qt.Key.Key_Escape)
    with qtbot.waitSignal(picker.cancelled, timeout=1000):
        picker.cancel_button.click()
    assert picker.back_button.text() == "‹ Back"
    with qtbot.waitSignal(picker.cancelled, timeout=1000):
        picker.back_button.click()
    assert picker.cancel_button.text() == "Cancel"


def test_use_button_names_the_family_and_is_disabled_without_rows(qtbot, picker, catalog):
    picker.open(PickRequest("latin"), None, set(), [])
    assert picker.use_button.text() == "Use Picker Latin" and picker.use_button.isEnabled()
    picker.search.setText("zeta")
    assert picker.use_button.text() == "Use Picker Zeta"
    with qtbot.waitSignal(picker.chosen, timeout=1000) as blocker:
        picker.use_button.click()
    assert blocker.args == [catalog["Z"]]
    picker.search.setText("no such font")
    assert not picker.use_button.isEnabled()


def test_candidate_is_debounced_and_carries_the_current_face(qtbot, picker, catalog):
    with qtbot.waitSignal(picker.candidateChanged, timeout=1000) as blocker:
        picker.open(PickRequest("any"), None, set(), [])
    assert blocker.args == [catalog["L"]]
    seen = []
    picker.candidateChanged.connect(seen.append)
    for _ in range(3):
        qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    assert seen == []                                           # nothing while the user is still moving
    qtbot.wait(300)
    assert seen == [catalog["Z"]] and picker.current_face() == catalog["Z"]
    with qtbot.waitSignal(picker.candidateChanged, timeout=1000) as blocker:
        picker.search.setText("no such font")
    assert blocker.args == [None]


def test_no_candidate_after_the_picker_is_closed_or_hidden(qtbot, picker):
    picker.open(PickRequest("any"), None, set(), [])
    seen = []
    picker.candidateChanged.connect(seen.append)
    picker.cancel_button.click()
    picker.show()
    picker.open(PickRequest("any"), None, set(), [])
    picker.hide()                                               # the app switched back to the recipe
    qtbot.wait(200)
    assert seen == []


# ----- catalog lifecycle -------------------------------------------------------------------------
def test_scan_lifecycle_texts(qtbot, catalog):
    picker = FontPicker()
    qtbot.addWidget(picker)
    picker.begin_scan()
    assert picker.status_label.text() == "Looking for fonts…" and not picker.progress.isHidden()
    picker.set_progress(340, 1101)
    assert picker.status_label.text() == "Looking for fonts… 340 / 1,101"
    assert (picker.progress.value(), picker.progress.maximum()) == (340, 1101)
    for face in catalog.values():
        picker.add_face(face)
    picker.end_scan(ScanResult(faces=list(catalog.values()), failed=[("C:/Fonts/bad.ttf", "TTLibError: bad")]))
    assert picker.progress.isHidden()
    assert picker.status_label.text() == "6 fonts · 1 file couldn't be read"
    assert picker.status_label.toolTip() == "C:/Fonts/bad.ttf: TTLibError: bad"
    picker.begin_scan()
    assert picker.faces_by_key() == {}
    picker.add_face(catalog["L"])
    failed = [(f"C:/Fonts/{i}.ttf", "OSError: gone") for i in range(3)]
    picker.end_scan(ScanResult(faces=[catalog["L"]], failed=failed))
    assert picker.status_label.text() == "1 font · 3 files couldn't be read"
    assert picker.status_label.toolTip().splitlines() == [f"{p}: {e}" for p, e in failed]
    picker.begin_scan()
    picker.end_scan(ScanResult())
    assert picker.status_label.text() == "0 fonts" and picker.status_label.toolTip() == ""


def test_rows_follow_a_running_scan_at_most_every_300_ms(qtbot, catalog):
    picker = FontPicker()
    qtbot.addWidget(picker)
    picker.begin_scan()
    picker.open(PickRequest("latin"), None, set(), [])
    assert picker.row_texts() == [] and picker.status_label.text() == "Looking for fonts…"
    picker.add_face(catalog["Z"])
    qtbot.wait(150)
    assert picker.row_texts() == []                                     # not per face: throttled
    qtbot.waitUntil(lambda: picker.row_texts() == ["ALL LATIN FONTS · 1", "Picker Zeta"], timeout=1000)
    assert picker.current_face() == catalog["Z"]
    picker.add_face(catalog["L"])                                       # sorts first; the current row stays
    picker.end_scan(ScanResult())                                       # the end refreshes at once
    assert picker.row_texts() == ["ALL LATIN FONTS · 2", "Picker Latin", "Picker Zeta"]
    assert picker.current_face() == catalog["Z"] and picker.status_label.text() == "2 fonts"


# ----- drawing ------------------------------------------------------------------------------------
def test_the_delegate_never_loads_a_file_while_painting(qtbot, tmp_path, monkeypatch):
    paths = [str(build_font(tmp_path / f"P{i}.ttf", f"Picker Paint {i}", "Regular", LATIN_CPS)) for i in range(3)]
    faces = [read_faces(p)[0] for p in paths]
    loader = fonts.font_loader()
    real = loader.family_for
    loads = []

    def spy(path, preferred=None):
        if not loader.is_loaded(path):
            loads.append(path)
        return real(path, preferred)

    monkeypatch.setattr(loader, "family_for", spy)
    picker = filled(qtbot, faces)
    picker.resize(420, 700)
    with qtbot.waitExposed(picker):
        picker.show()                                       # nothing to draw yet: the picker is not open
    picker.open(PickRequest("latin"), None, set(), [])
    picker.view.viewport().repaint()                        # paints the rows synchronously
    assert loads == []
    assert sorted(picker.pending_fonts()) == sorted(paths)
    assert picker.delegate.face_font(faces[0], 13) is None  # not loaded yet: the UI font draws it
    passes = []
    picker.delegate.font_timer.timeout.connect(lambda: passes.append(len(loads)))
    qtbot.waitUntil(lambda: not picker.pending_fonts(), timeout=1000)
    assert passes == [1, 2, 3] and sorted(loads) == sorted(paths)   # one file per event-loop pass
    font = picker.delegate.face_font(faces[0], 13)
    assert font is not None and font.family() == "Picker Paint 0" and font.pointSizeF() == 13
    assert picker.delegate.face_font(faces[0], 13) is font          # cached per (face, size)
    picker.view.viewport().repaint()
    assert len(loads) == 3


def test_apply_theme_dark(qtbot, picker, catalog):
    assert picker.objectName() == "picker" and picker.delegate.theme is LIGHT
    picker.open(PickRequest("latin"), None, {catalog["L"].key}, [catalog["Z"]])
    picker.apply_theme(DARK)
    assert picker.styleSheet() == DARK.render(STYLE) and DARK.surface in picker.styleSheet()
    assert picker.delegate.theme is DARK
    picker.resize(420, 600)
    assert not picker.grab().isNull()                       # paints headers, tags and rows in the dark theme
    picker.apply_theme(LIGHT)
    assert picker.styleSheet() == LIGHT.render(STYLE) and picker.delegate.theme is LIGHT
