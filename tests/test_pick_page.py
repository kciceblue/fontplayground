from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from fontplayground.catalog.face import FontFace, read_faces
from fontplayground.catalog.scanner import ScanResult
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.pick_page import (ADD_TEXT, ADDED_TEXT, COL_FORMAT, COL_NAME, COL_SCRIPTS, PickPage,
                                         default_face, face_info_text, family_badge, family_format)
from fontplayground.ui.preview import PreviewWidget
from tests.fixtures import cps, fake_face


def all_faces(font_dir: Path) -> list[FontFace]:
    faces: list[FontFace] = []
    for p in sorted(font_dir.iterdir()):
        faces.extend(read_faces(p))
    return faces


def face_at(faces: list[FontFace], name: str, index: int = 0) -> FontFace:
    return next(f for f in faces if Path(f.path).name == name and f.index == index)


def family_texts(page: PickPage) -> list[str]:
    return [page.tree.topLevelItem(i).text(COL_NAME) for i in range(page.tree.topLevelItemCount())]


def combo_texts(page: PickPage) -> list[str]:
    return [page.style_combo.itemText(i) for i in range(page.style_combo.count())]


@pytest.fixture
def faces(font_dir):
    return all_faces(font_dir)


@pytest.fixture
def model(qapp):
    return ForgeModel()


@pytest.fixture
def page(qtbot, model, faces):
    p = PickPage(model, PreviewWidget(sizes=(12,)))
    qtbot.addWidget(p)
    p.begin_scan()
    for f in faces:
        p.add_face(f)
    p.end_scan(ScanResult(faces=faces))
    model.set_catalog(p.faces_by_key())
    return p


# ----- tree -------------------------------------------------------------------------------------
def test_families_collapse_to_one_row_with_badges(page, faces):
    assert family_texts(page) == ["Fixture A", "Fixture B", "Fixture C", "Fixture K", "Fixture V"]
    for i in range(page.tree.topLevelItemCount()):
        assert not page.tree.topLevelItem(i).isExpanded()
    a, b, c = (page.family_item(f) for f in ("Fixture A", "Fixture B", "Fixture C"))
    assert a.childCount() == 2 and c.childCount() == 2 and b.childCount() == 1   # the TTC faces merge in
    assert a.data(COL_NAME, Qt.ItemDataRole.UserRole) is None
    assert a.text(COL_SCRIPTS) == "Latin"
    assert b.text(COL_SCRIPTS) == "Han · CJK symbols · Latin"      # non-Latin first, Latin last
    assert c.text(COL_SCRIPTS) == "Greek · Symbols · Latin"
    assert b.toolTip(COL_SCRIPTS) == "Covers: Latin, Han, CJK symbols & fullwidth"
    assert a.text(COL_FORMAT) == "TTF/TTC" and b.text(COL_FORMAT) == "OTF"
    assert page.family_item("Fixture V").text(COL_FORMAT) == "VAR"
    assert len(page.faces_by_key()) == 7
    # face rows: style, nothing, format; the key in UserRole; the path as tooltip on the format column
    fa = face_at(faces, "A.ttf")
    row = page.item_for(fa.key)
    assert row.parent() is a
    assert (row.text(COL_NAME), row.text(COL_SCRIPTS), row.text(COL_FORMAT)) == ("Regular", "", "TTF")
    assert row.data(COL_NAME, Qt.ItemDataRole.UserRole) == fa.key
    assert row.toolTip(COL_FORMAT) == fa.path
    assert page.item_for(face_at(faces, "T.ttc", 0).key).text(COL_FORMAT) == "TTC"
    assert page.item_for(("nope.ttf", 0)) is None and page.family_item("Nope") is None


def test_family_badge_and_format_helpers():
    assert family_badge(["latin"]) == "Latin"
    assert family_badge(["han", "latin", "kana", "cjk_symbols"]) == "Kana · Han · CJK symbols · Latin"  # GROUPS order
    assert family_badge(["symbols", "han", "greek", "cyrillic", "hebrew", "arabic", "latin"]) == \
        "Greek · Cyrillic · Hebrew · Arabic · +2 · Latin"
    assert family_badge(["han", "greek", "cyrillic", "hebrew", "arabic"]) == "Greek · Cyrillic · Hebrew · Arabic · +1"
    assert family_badge([]) == ""
    ttf = fake_face({0x41}, path="a.ttf")
    otf = fake_face({0x41}, path="b.otf", outline="CFF")
    assert family_format([ttf, ttf, otf]) == "TTF/OTF"


def test_faces_sorted_by_weight_then_italic(page):
    page.add_face(fake_face({0x41}, path="z-black.ttf", family="Fixture Z", style="Black", weight=900))
    page.add_face(fake_face({0x41}, path="z-light.ttf", family="Fixture Z", style="Light", weight=300))
    page.add_face(fake_face({0x41}, path="z-regular.ttf", family="Fixture Z", style="Regular", weight=400))
    fam = page.family_item("Fixture Z")
    assert [fam.child(i).text(COL_NAME) for i in range(fam.childCount())] == ["Light", "Regular", "Black"]
    assert family_texts(page)[-1] == "Fixture Z"


# ----- filters ------------------------------------------------------------------------------------
def test_quick_filter_keeps_families_with_the_script(page):
    page.add_face(fake_face(cps("aあ"), path="jp.ttf", family="Fixture J"))
    assert page.visible_families() == ["Fixture A", "Fixture B", "Fixture C", "Fixture J", "Fixture K", "Fixture V"]
    assert page.filter_buttons["Any script"].isChecked() and page.script_filter() is None
    page.filter_buttons["Chinese"].click()
    assert page.script_filter() == "han"
    assert page.visible_families() == ["Fixture B"]
    assert not page.item_for(next(iter(page.faces_by_key()))).parent().isExpanded()  # families stay collapsed
    page.filter_buttons["Japanese"].click()
    assert page.visible_families() == ["Fixture J"]
    page.filter_buttons["Korean"].click()
    assert page.visible_families() == []
    page.filter_buttons["Symbols"].click()
    assert page.visible_families() == ["Fixture C"]
    page.filter_buttons["Any script"].click()
    assert len(page.visible_families()) == 6
    # the programmatic way checks the matching button
    page.set_script_filter("han")
    assert page.filter_buttons["Chinese"].isChecked() and page.visible_families() == ["Fixture B"]
    page.set_script_filter(None)
    assert page.filter_buttons["Any script"].isChecked() and len(page.visible_families()) == 6
    with pytest.raises(ValueError):
        page.set_script_filter("klingon")
    # a face that arrives during a scan respects the active filter
    page.set_script_filter("hangul")
    page.add_face(fake_face(cps("한"), path="kr.ttf", family="Fixture H"))
    assert page.visible_families() == ["Fixture H"]


def test_search_filter(page, faces):
    page.apply_filter("fixture b")
    assert page.visible_families() == ["Fixture B"]
    assert not page.family_item("Fixture B").isExpanded()   # the family name matched: no need to open it
    # a style match opens the family so the matching face is visible, and closes it again afterwards
    page.search.setText("BOLD")
    assert page.visible_families() == ["Fixture B"]
    assert page.family_item("Fixture B").isExpanded()
    assert not page.item_for(face_at(faces, "B.otf").key).isHidden()
    page.search.setText("")
    assert page.visible_families() == ["Fixture A", "Fixture B", "Fixture C", "Fixture K", "Fixture V"]
    assert not page.family_item("Fixture B").isExpanded()
    # search and quick filter combine
    page.search.setText("fixture")
    page.filter_buttons["Chinese"].click()
    assert page.visible_families() == ["Fixture B"]
    page.search.setText("fixture a")
    assert page.visible_families() == []


# ----- preview and coverage -------------------------------------------------------------------------
def test_family_row_previews_default_face_and_coverage_against_empty_tray(page, faces, model):
    assert page.current_face() is None and page.coverage_label.text() == ""
    assert not page.add_button.isEnabled()
    model.set_sample_text("abc 漢字 →")
    shown = []
    page.currentFaceChanged.connect(shown.append)
    page.tree.setCurrentItem(page.family_item("Fixture B"))
    b = face_at(faces, "B.otf")
    assert page.current_face() == b and shown == [b]
    assert page.preview.current_family() == "Fixture B"
    assert page.family_label.text() == "Fixture B"
    assert combo_texts(page) == ["Bold"] and page.style_combo.currentText() == "Bold"
    assert page.licence_label.text() == "licence: installable" and page.licence_label.property("restricted") is False
    assert page.coverage_label.text() == \
        "Covers Latin, Han, CJK symbols & fullwidth · Missing from your sample: c → 字"
    assert "#b3261e" in page.coverage_label.styleSheet()
    assert page.coverage_label.toolTip() == "Not in this font: c → 字"
    assert page.details_label.isHidden() and page.details_label.text() == face_info_text(b)
    assert page.add_button.isEnabled() and page.add_button.text() == ADD_TEXT
    # the sample drives the line: a sample the face fully covers turns it green
    model.set_sample_text("ab 漢")
    assert page.coverage_label.text() == "Covers Latin, Han, CJK symbols & fullwidth · Covers your whole sample"
    assert "#2f8f46" in page.coverage_label.styleSheet()
    # the restricted licence is flagged
    page.tree.setCurrentItem(page.family_item("Fixture C"))
    assert page.licence_label.text() == "licence: restricted" and page.licence_label.property("restricted") is True


def test_coverage_says_what_a_face_would_add_once_the_tray_has_fonts(page, faces, model):
    a, b, c = (face_at(faces, n) for n in ("A.ttf", "B.otf", "C.ttf"))
    model.add(a)
    page.tree.setCurrentItem(page.family_item("Fixture B"))
    assert page.coverage_label.text() == \
        "Covers Latin, Han, CJK symbols & fullwidth · Would add to your sample: Han, CJK symbols & fullwidth"
    assert "#2f8f46" in page.coverage_label.styleSheet()
    page.tree.setCurrentItem(page.family_item("Fixture K"))   # Latin only: nothing new
    assert page.coverage_label.text() == "Covers Latin · Adds nothing your fonts do not already cover"
    assert "#777777" in page.coverage_label.styleSheet()
    page.tree.setCurrentItem(page.family_item("Fixture A"))   # the face itself is in the tray
    assert page.current_face() == a
    assert page.coverage_label.text() == "Covers Latin · In your materials"
    # the line follows the tray without reselecting
    page.tree.setCurrentItem(page.family_item("Fixture B"))
    model.add(c)
    assert "Would add to your sample: Han, CJK symbols & fullwidth" in page.coverage_label.text()
    model.add(b)
    assert page.coverage_label.text().endswith("· In your materials")
    model.remove(a.key)
    model.remove(c.key)
    model.remove(b.key)
    assert "Missing from your sample" in page.coverage_label.text()


def test_face_row_previews_that_face_and_syncs_the_combo(page, faces, model):
    fam = page.family_item("Fixture Z") if page.family_item("Fixture Z") else None
    assert fam is None
    light = fake_face({0x41}, path="z-light.ttf", family="Fixture Z", style="Light", weight=300)
    black = fake_face({0x41}, path="z-black.ttf", family="Fixture Z", style="Black", weight=900)
    regular = fake_face({0x41}, path="z-regular.ttf", family="Fixture Z", style="Regular", weight=400)
    for f in (light, black, regular):
        page.add_face(f)
    fam = page.family_item("Fixture Z")
    # no Main: the default is the weight closest to 400
    page.tree.setCurrentItem(fam)
    assert page.current_face() == regular and page.style_combo.currentText() == "Regular"
    assert combo_texts(page) == ["Light", "Regular", "Black"]
    # Main is Bold (700): Black (900) is closer than Regular (400)
    model.add(face_at(faces, "B.otf"))
    page.tree.setCurrentItem(page.family_item("Fixture A"))
    page.tree.setCurrentItem(fam)
    assert page.current_face() == black and page.style_combo.currentText() == "Black"
    # a face row previews exactly that face
    page.tree.setCurrentItem(page.item_for(light.key))
    assert page.current_face() == light and page.style_combo.currentText() == "Light"
    assert page.family_label.text() == "Fixture Z"
    # the combo changes the previewed face and, since a face row is current, the tree follows
    page.style_combo.setCurrentText("Black")
    assert page.current_face() == black
    assert page.tree.currentItem() is page.item_for(black.key)
    assert combo_texts(page) == ["Light", "Regular", "Black"]
    # with the family row current the tree stays on the family row
    page.tree.setCurrentItem(fam)
    page.style_combo.setCurrentText("Light")
    assert page.current_face() == light and page.tree.currentItem() is fam
    # leaving the tree clears the right pane
    page.tree.setCurrentItem(None)
    assert page.current_face() is None and page.family_label.text() == ""
    assert page.preview.current_family() is None and combo_texts(page) == []
    assert page.style_combo.isHidden() and page.licence_label.isHidden()


def test_default_face_helper():
    light = fake_face({0x41}, path="l.ttf", style="Light", weight=300)
    bold = fake_face({0x41}, path="b.ttf", style="Bold", weight=700)
    cff2 = fake_face({0x41}, path="x.otf", style="Regular", weight=400, outline="CFF2")
    assert default_face([], None) is None
    assert default_face([light, bold], None) == light            # 300 is closer to 400 than 700
    assert default_face([light, bold], bold) == bold
    assert default_face([cff2, light, bold], None) == light      # unsupported faces are skipped...
    assert default_face([cff2], None) == cff2                    # ...unless there is nothing else


# ----- add button -----------------------------------------------------------------------------------
def test_add_button_toggles_membership_and_its_text(page, faces, model):
    a = face_at(faces, "A.ttf")
    b = face_at(faces, "B.otf")
    page.select_face(a.key)
    assert page.add_button.isEnabled() and page.add_button.text() == ADD_TEXT and not page.add_button.isChecked()
    assert page.add_button.toolTip() == "Add Fixture A Regular to your materials"
    page.add_button.click()
    assert model.keys() == [a.key]
    assert page.add_button.text() == ADDED_TEXT and page.add_button.isChecked()
    assert page.add_button.toolTip() == "Remove Fixture A Regular from your materials"
    assert page.family_item("Fixture A").text(COL_FORMAT) == "TTF/TTC ✓"
    assert page.family_item("Fixture A").foreground(COL_FORMAT).color().name() == "#2f8f46"
    assert page.family_item("Fixture B").text(COL_FORMAT) == "OTF"
    page.add_button.click()
    assert model.keys() == [] and page.add_button.text() == ADD_TEXT and not page.add_button.isChecked()
    assert page.family_item("Fixture A").text(COL_FORMAT) == "TTF/TTC"
    # changes made elsewhere (the tray) show up too
    model.add(b)
    assert page.family_item("Fixture B").text(COL_FORMAT) == "OTF ✓"
    assert page.add_button.text() == ADD_TEXT    # A is shown, and A is not in the tray
    page.select_face(b.key)
    assert page.add_button.text() == ADDED_TEXT and page.add_button.isChecked()
    model.remove(b.key)
    assert page.add_button.text() == ADD_TEXT and page.family_item("Fixture B").text(COL_FORMAT) == "OTF"
    # Enter / double-click on a face row toggles it as well
    page.tree.itemActivated.emit(page.item_for(a.key), 0)
    assert model.keys() == [a.key] and page.current_face() == a
    page.tree.itemActivated.emit(page.family_item("Fixture B"), 0)   # family rows only expand
    assert model.keys() == [a.key]


def test_unsupported_face_is_greyed_selectable_but_not_addable(page, model):
    bad = fake_face({0x41}, path="cff2.otf", family="Fixture Z", style="Regular", outline="CFF2")
    good = fake_face({0x41}, path="light.ttf", family="Fixture Z", style="Light", weight=300)
    page.add_face(bad)
    page.add_face(good)
    row = page.item_for(bad.key)
    assert not row.isDisabled()
    assert row.toolTip(COL_NAME) == "CFF2 outlines are not supported"
    grey = page.tree.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert row.foreground(COL_NAME).color() == grey and row.foreground(COL_FORMAT).color() == grey
    assert page.item_for(good.key).foreground(COL_NAME).color() != grey
    page.tree.setCurrentItem(row)
    assert page.tree.currentItem() is row and page.current_face() == bad
    assert page.details_label.text().startswith("cff2.otf (face 0)")
    assert "CFF2 outlines" in page.add_button.text() and not page.add_button.isEnabled()
    assert page.add_button.toolTip() == "CFF2 outlines are not supported"
    assert combo_texts(page) == ["Light"] and page.style_combo.currentIndex() == -1   # only supported faces
    page.add_button.click()
    assert model.keys() == []
    # the family row skips it in favour of the supported face
    page.tree.setCurrentItem(page.family_item("Fixture Z"))
    assert page.current_face() == good and page.add_button.isEnabled()


# ----- select_face, details, sample text ----------------------------------------------------------------
def test_select_face_expands_previews_and_syncs(page, faces):
    b = face_at(faces, "B.otf")
    t1 = face_at(faces, "T.ttc", 1)   # the second face of the collection lives under Fixture C
    assert not page.family_item("Fixture B").isExpanded()
    assert page.select_face(b.key)
    assert page.family_item("Fixture B").isExpanded()
    assert page.tree.currentItem() is page.item_for(b.key)
    assert page.current_face() == b and page.preview.current_family() == "Fixture B"
    assert page.style_combo.currentText() == "Bold"
    assert page.select_face(t1.key)
    assert page.family_item("Fixture C").isExpanded() and page.current_face() == t1
    assert page.family_label.text() == "Fixture C" and page.style_combo.currentText() == "Regular"
    assert page.style_combo.currentData() == t1.key
    assert not page.select_face(("nope.ttf", 0))
    assert page.current_face() == t1
    assert page.select_face(t1.key)   # already current: still fine


def test_details_toggle_reveals_the_info_strip(page, faces):
    page.select_face(face_at(faces, "V.ttf").key)
    assert page.details_label.isHidden() and page.details_button.arrowType() == Qt.ArrowType.RightArrow
    page.details_button.click()
    assert not page.details_label.isHidden() and page.details_button.arrowType() == Qt.ArrowType.DownArrow
    text = page.details_label.text()
    assert "Axes: wght 100–900 (default 400)" in text and "Format: VAR / glyf outlines" in text
    assert "Embedding: installable" in text
    page.details_button.click()
    assert page.details_label.isHidden()


def test_sample_text_flows_both_ways(page, model):
    assert page.preview.sample_text() == model.sample_text
    page.preview.editor.setPlainText("typed here")
    assert model.sample_text == "typed here"
    model.set_sample_text("set on the model")
    assert page.preview.sample_text() == "set on the model"


# ----- scan lifecycle -------------------------------------------------------------------------------------
def test_scan_lifecycle_progress_and_status(qtbot, model, faces):
    page = PickPage(model, PreviewWidget(sizes=(12,)))
    qtbot.addWidget(page)
    assert page.progress.isHidden() and page.status_label.text() == ""
    page.begin_scan()
    assert not page.progress.isHidden() and page.progress.value() == 0
    assert page.tree.topLevelItemCount() == 0 and page.status_label.text() == "Scanning fonts…"
    for f in faces:
        page.add_face(f)
    page.set_progress(3, 5)
    assert (page.progress.value(), page.progress.maximum()) == (3, 5)
    assert page.status_label.text() == "Scanning fonts… 3 / 5"
    page.end_scan(ScanResult(faces=faces, failed=[("bad.ttf", "TTLibError: boom")]))
    assert page.progress.isHidden()
    assert page.status_label.text() == "7 fonts in 5 families, 1 unreadable file"
    assert page.status_label.toolTip() == "bad.ttf: TTLibError: boom"
    page.end_scan(ScanResult(faces=faces))
    assert page.status_label.text() == "7 fonts in 5 families" and page.status_label.toolTip() == ""
    page.add_face(faces[0])   # a duplicate is ignored
    assert len(page.faces_by_key()) == 7


def test_rescan_keeps_the_filter_and_restores_the_previewed_face(page, faces):
    b = face_at(faces, "B.otf")
    page.select_face(b.key)
    page.filter_buttons["Chinese"].click()
    page.begin_scan()
    assert page.faces_by_key() == {} and page.current_face() is None
    assert page.preview.current_family() is None
    for f in faces:
        page.add_face(f)
    page.end_scan(ScanResult(faces=faces))
    assert page.visible_families() == ["Fixture B"]
    assert page.current_face() == b and page.tree.currentItem() is page.item_for(b.key)
    assert page.preview.current_family() == "Fixture B"
    # a face that vanished is simply not shown again
    page.begin_scan()
    for f in faces:
        if f.key != b.key:
            page.add_face(f)
    page.end_scan(ScanResult(faces=[f for f in faces if f.key != b.key]))
    assert page.current_face() is None and page.visible_families() == []
