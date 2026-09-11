from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from fontplayground.catalog.face import FontFace, read_faces
from fontplayground.catalog.scanner import ScanResult
from fontplayground.ui.fonts_tab import FontsTab, face_info_text
from fontplayground.ui.preview import PreviewWidget
from tests.fixtures import fake_face


def all_faces(font_dir: Path) -> list[FontFace]:
    faces: list[FontFace] = []
    for p in sorted(font_dir.iterdir()):
        faces.extend(read_faces(p))
    return faces


def face_at(faces: list[FontFace], name: str, index: int = 0) -> FontFace:
    return next(f for f in faces if Path(f.path).name == name and f.index == index)


def family_texts(tab: FontsTab) -> list[str]:
    return [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]


def family_item(tab: FontsTab, family: str):
    return next(tab.tree.topLevelItem(i) for i in range(tab.tree.topLevelItemCount())
                if tab.tree.topLevelItem(i).text(0) == family)


@pytest.fixture
def tab(qtbot, font_dir):
    t = FontsTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(t)
    t.begin_scan()
    faces = all_faces(font_dir)
    for f in faces:
        t.add_face(f)
    t.end_scan(ScanResult(faces=faces))
    t.fixture_faces = faces
    return t


# 1
def test_tree_groups_faces_by_family_sorted(tab):
    assert tab.tree.topLevelItemCount() == 4
    assert family_texts(tab) == ["Fixture A", "Fixture B", "Fixture C", "Fixture V"]
    # the two TTC faces merge into the A and C families
    assert family_item(tab, "Fixture A").childCount() == 2
    assert family_item(tab, "Fixture C").childCount() == 2
    assert family_item(tab, "Fixture B").childCount() == 1
    assert len(tab.faces_by_key()) == 6
    a = face_at(tab.fixture_faces, "A.ttf")
    row = tab.item_for(a.key)
    assert row.text(0) == "Regular" and row.text(1) == "TTF"
    assert row.data(0, Qt.ItemDataRole.UserRole) == a.key
    assert row.toolTip(1) == a.path
    assert row.checkState(0) == Qt.CheckState.Unchecked
    assert row.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert not (family_item(tab, "Fixture A").flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert family_item(tab, "Fixture A").data(0, Qt.ItemDataRole.UserRole) is None
    assert tab.item_for(face_at(tab.fixture_faces, "T.ttc", 0).key).text(1) == "TTC"
    assert tab.item_for(face_at(tab.fixture_faces, "V.ttf").key).text(1) == "VAR"
    assert tab.item_for(face_at(tab.fixture_faces, "B.otf").key).text(1) == "OTF"


# 2
def test_ticking_emits_selection_in_tick_order(qtbot, tab):
    a = face_at(tab.fixture_faces, "A.ttf")
    b = face_at(tab.fixture_faces, "B.otf")
    with qtbot.waitSignal(tab.selectionChanged) as blocker:
        tab.item_for(a.key).setCheckState(0, Qt.CheckState.Checked)
    assert blocker.args == [[a]]
    with qtbot.waitSignal(tab.selectionChanged) as blocker:
        tab.item_for(b.key).setCheckState(0, Qt.CheckState.Checked)
    assert blocker.args == [[a, b]]
    assert tab.selected_faces() == [a, b]
    assert tab.selected_label.text() == "Selected: 2"
    with qtbot.waitSignal(tab.selectionChanged) as blocker:
        tab.item_for(a.key).setCheckState(0, Qt.CheckState.Unchecked)
    assert blocker.args == [[b]]
    assert tab.selected_faces() == [b]
    assert tab.selected_label.text() == "Selected: 1"


# 3
def test_filter_hides_families_without_matches(tab):
    tab.apply_filter("fixture b")
    assert family_item(tab, "Fixture A").isHidden()
    assert not family_item(tab, "Fixture B").isHidden()
    assert not tab.item_for(face_at(tab.fixture_faces, "B.otf").key).isHidden()
    # matches on style too, case-insensitively
    tab.apply_filter("BOLD")
    assert family_texts_visible(tab) == ["Fixture B"]
    tab.apply_filter("")
    assert family_texts_visible(tab) == ["Fixture A", "Fixture B", "Fixture C", "Fixture V"]
    # typing in the search box drives the same filter
    tab.search.setText("fixture v")
    assert family_texts_visible(tab) == ["Fixture V"]


def family_texts_visible(tab: FontsTab) -> list[str]:
    return [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())
            if not tab.tree.topLevelItem(i).isHidden()]


# 4
def test_set_ticked_replaces_ticks_and_emits_once(tab):
    a = face_at(tab.fixture_faces, "A.ttf")
    b = face_at(tab.fixture_faces, "B.otf")
    c = face_at(tab.fixture_faces, "C.ttf")
    tab.item_for(c.key).setCheckState(0, Qt.CheckState.Checked)
    calls: list[list[FontFace]] = []
    tab.selectionChanged.connect(lambda faces: calls.append(list(faces)))
    tab.set_ticked([b.key, a.key, ("missing.ttf", 0)])
    assert tab.selected_faces() == [b, a]
    assert calls == [[b, a]]
    assert tab.item_for(c.key).checkState(0) == Qt.CheckState.Unchecked
    assert tab.item_for(a.key).checkState(0) == Qt.CheckState.Checked
    assert tab.item_for(b.key).checkState(0) == Qt.CheckState.Checked
    assert tab.selected_label.text() == "Selected: 2"


# 5
def test_current_face_drives_preview_and_info(tab):
    a = face_at(tab.fixture_faces, "A.ttf")
    tab.tree.setCurrentItem(tab.item_for(a.key))
    assert tab.preview.current_family() == "Fixture A"
    info = tab.info_label.text()
    assert "Glyphs: 6" in info
    assert info.splitlines()[0] == f"{a.path} (face 0)"
    assert "Format: TTF / glyf outlines" in info
    assert "Axes: none" in info
    assert "Scripts: Latin" in info
    assert "Embedding: installable" in info
    # a family row clears the preview and the info strip
    tab.tree.setCurrentItem(family_item(tab, "Fixture A"))
    assert tab.preview.current_family() is None
    assert tab.info_label.text() == ""


def test_info_text_for_variable_and_restricted_faces(tab):
    v = face_at(tab.fixture_faces, "V.ttf")
    c = face_at(tab.fixture_faces, "C.ttf")
    assert "Axes: wght 100–900 (default 400)" in face_info_text(v)
    assert "Format: VAR / glyf outlines" in face_info_text(v)
    assert "Embedding: restricted" in face_info_text(c)
    assert "Scripts: Latin, Greek, Punctuation & symbols" in face_info_text(c)


def test_scan_lifecycle_progress_and_status(qtbot, font_dir):
    tab = FontsTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(tab)
    assert tab.progress.isHidden()
    tab.begin_scan()
    assert not tab.progress.isHidden() and tab.progress.value() == 0
    assert tab.tree.topLevelItemCount() == 0
    faces = all_faces(font_dir)
    for f in faces:
        tab.add_face(f)
    tab.set_progress(3, 5)
    assert (tab.progress.value(), tab.progress.maximum()) == (3, 5)
    tab.end_scan(ScanResult(faces=faces, failed=[("bad.ttf", "TTLibError: boom")]))
    assert tab.progress.isHidden()
    assert tab.status_label.text() == "6 faces in 4 families, 1 unreadable file"
    assert "bad.ttf: TTLibError: boom" in tab.status_label.toolTip()
    tab.end_scan(ScanResult(faces=faces))
    assert tab.status_label.text() == "6 faces in 4 families"


def test_rescan_clears_tree_and_restores_ticks(qtbot, tab):
    a = face_at(tab.fixture_faces, "A.ttf")
    tab.item_for(a.key).setCheckState(0, Qt.CheckState.Checked)
    calls: list[list[FontFace]] = []
    tab.selectionChanged.connect(lambda faces: calls.append(list(faces)))
    tab.begin_scan()
    assert tab.faces_by_key() == {} and tab.selected_faces() == []
    assert tab.selected_label.text() == "Selected: 0"
    assert calls == []
    for f in tab.fixture_faces:
        tab.add_face(f)
    tab.end_scan(ScanResult(faces=tab.fixture_faces))
    assert tab.selected_faces() == [a]
    assert tab.item_for(a.key).checkState(0) == Qt.CheckState.Checked
    assert calls == [[a]]


def test_unsupported_face_is_disabled_with_reason(qtbot):
    tab = FontsTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(tab)
    tab.begin_scan()
    bad = fake_face({0x41}, path="cff2.otf", family="Fixture Z", style="Regular", outline="CFF2")
    heavy = fake_face({0x41}, path="heavy.ttf", family="Fixture Z", style="Black", weight=900)
    light = fake_face({0x41}, path="light.ttf", family="Fixture Z", style="Light", weight=300)
    for f in (bad, heavy, light):
        tab.add_face(f)
    row = tab.item_for(bad.key)
    assert row.isDisabled()
    assert row.toolTip(0) == "CFF2 outlines are not supported"
    assert not tab.item_for(light.key).isDisabled()
    fam = family_item(tab, "Fixture Z")
    assert [fam.child(i).text(0) for i in range(fam.childCount())] == ["Light", "Regular", "Black"]


def test_filter_applies_to_faces_added_during_scan(tab):
    tab.apply_filter("fixture z")
    assert family_texts_visible(tab) == []
    tab.add_face(fake_face({0x41}, path="z.ttf", family="Fixture Z", style="Regular"))
    assert family_texts_visible(tab) == ["Fixture Z"]
    tab.add_face(fake_face({0x41}, path="y.ttf", family="Fixture Y", style="Regular"))
    assert family_texts_visible(tab) == ["Fixture Z"]
    assert family_texts(tab) == ["Fixture A", "Fixture B", "Fixture C", "Fixture V", "Fixture Y", "Fixture Z"]


def test_buttons_emit_signals(qtbot, tab):
    with qtbot.waitSignal(tab.rescanRequested):
        tab.rescan_button.click()
    with qtbot.waitSignal(tab.addFolderRequested):
        tab.add_folder_button.click()
    with qtbot.waitSignal(tab.goToForge):
        tab.forge_button.click()
