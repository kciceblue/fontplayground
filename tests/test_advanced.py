import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox

from fontplayground.catalog.face import read_faces
from fontplayground.engine.scripts import GROUPS, LABELS
from fontplayground.engine.spec import ForgeReport, MaterialReport
from fontplayground.ui.advanced import (COL_COUNTS, COL_DRAWN_BY, COL_SCRIPT, NO_BUILD_TEXT, NO_COUNT, NOBODY,
                                        SHOW_ALL_TEXT, SHOW_COVERED_TEXT, AdvancedDialog, short_names)
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.theme import DARK, LIGHT
from tests.fixtures import cps, fake_face


class StubController(QObject):
    """What the dialog needs of the build controller: `changed`, `report` and `error_detail`."""
    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.report: ForgeReport | None = None
        self.error_detail: str | None = None


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    return a, b


@pytest.fixture
def model(qapp, faces):
    m = ForgeModel()
    m.set_catalog({f.key: f for f in faces})
    return m


@pytest.fixture
def controller(qapp):
    return StubController()


@pytest.fixture
def dialog(qtbot, model, controller, faces):
    a, b = faces
    model.add(a)
    model.add(b)
    d = AdvancedDialog(model, controller)
    qtbot.addWidget(d)
    return d


def test_short_names_use_the_family_unless_two_fonts_share_it():
    a = fake_face(cps("a"), path="a.ttf", family="Segoe UI", style="Regular")
    b = fake_face(cps("b"), path="b.ttf", family="YaHei", style="Regular")
    b2 = fake_face(cps("c"), path="b2.ttf", family="YaHei", style="Bold")
    assert short_names([a, b]) == {a.key: "Segoe UI", b.key: "YaHei"}
    assert short_names([a, b, b2]) == {a.key: "Segoe UI", b.key: "YaHei Regular", b2.key: "YaHei Bold"}


def test_dialog_is_titled_advanced_and_not_modal(dialog):
    assert dialog.windowTitle() == "Advanced" and not dialog.isModal()
    assert dialog.who_title.text() == "Who draws what" and dialog.build_title.text() == "Last build"


def test_table_lists_only_covered_scripts_until_show_all(dialog):
    groups = dialog.table_groups()
    assert groups == ["latin", "han", "cjk_symbols"] and dialog.table.rowCount() == 3
    assert [dialog.table.horizontalHeaderItem(c).text() for c in range(3)] == ["Script", "Drawn by", "Characters"]
    assert [dialog.cell_text(g, COL_SCRIPT) for g in groups] == ["Latin", "Han", "CJK symbols & fullwidth"]
    assert dialog.cell_text("latin", COL_COUNTS) == "Fixture A 5 · Fixture B 2"
    assert dialog.cell_text("han", COL_COUNTS) == "Fixture B 1"
    assert dialog.cell_text("han", COL_DRAWN_BY) == "Auto → Fixture B Bold"
    latin = dialog.supplier_combo("latin")
    assert isinstance(latin, QComboBox)
    assert [latin.itemText(i) for i in range(latin.count())] == ["Auto → Fixture A Regular", "Fixture A Regular",
                                                                  "Fixture B Bold"]

    assert dialog.show_all_button.text() == SHOW_ALL_TEXT == "Show all 15 scripts"
    dialog.show_all_button.click()
    assert dialog.show_all_button.text() == SHOW_COVERED_TEXT == "Show only covered scripts"
    assert dialog.table_groups() == [g.id for g in GROUPS] and dialog.table.rowCount() == 15
    assert dialog.cell_text("arabic", COL_SCRIPT) == LABELS["arabic"]
    assert dialog.cell_text("arabic", COL_DRAWN_BY) == NOBODY == "nobody"
    assert dialog.cell_text("arabic", COL_COUNTS) == NO_COUNT == "—"
    assert dialog.supplier_combo("arabic") is None and dialog.supplier_combo("han") is not None
    dialog.show_all_button.click()
    assert dialog.table_groups() == ["latin", "han", "cjk_symbols"]


def test_choosing_a_font_pins_the_script_and_auto_unpins(dialog, model, faces):
    a, b = faces
    dialog.supplier_combo("latin").setCurrentIndex(2)       # Fixture B Bold
    assert model.pins["latin"] == b.key and model.script_rules()["latin"] == 1
    combo = dialog.supplier_combo("latin")                   # rebuilt from the model
    assert combo.currentText() == "Fixture B Bold"
    assert dialog.cell_text("latin", COL_COUNTS) == "Fixture B 2 · Fixture A 5"   # the rule's font first
    combo.setCurrentIndex(0)
    assert model.pins["latin"] is None and dialog.supplier_combo("latin").currentIndex() == 0


def test_table_follows_the_model(dialog, model, faces):
    a, b = faces
    model.remove(b.key)
    assert dialog.table_groups() == ["latin"]
    model.reset()
    assert dialog.table_groups() == [] and dialog.table.rowCount() == 0


def test_line_spacing_combo_sets_the_base(dialog, model, faces):
    a, b = faces
    combo = dialog.base_combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Main font", "Fixture A Regular", "Fixture B Bold"]
    assert combo.currentIndex() == 0 and combo.isEnabled()
    combo.setCurrentIndex(2)
    assert model.base_key == b.key
    model.move(b.key, 0)                                     # the choice follows the font, not the position
    assert dialog.base_combo.currentText() == "Fixture B Bold"
    dialog.base_combo.setCurrentIndex(0)
    assert model.base_key is None
    model.reset()
    assert dialog.base_combo.count() == 1 and not dialog.base_combo.isEnabled()


def test_defaults_set_the_model(dialog, model):
    weights = dialog.default_weight_combo
    assert [weights.itemText(i) for i in range(weights.count())][:2] == ["As is", "Light (300)"]
    assert weights.count() == 7 and weights.currentText() == "As is"
    spin = dialog.default_scale_spin
    assert (spin.minimum(), spin.maximum(), spin.value(), spin.suffix()) == (10, 1000, 100, " %")
    assert dialog.defaults_note.text() == "For fonts without their own setting."
    weights.setCurrentIndex(5)
    assert (model.default_weight, model.default_scale) == (700, 1.0)
    spin.setValue(90)
    assert (model.default_weight, model.default_scale) == (700, 0.9)
    weights.setCurrentIndex(0)
    assert (model.default_weight, model.default_scale) == (None, 0.9)
    model.set_defaults(650, 1.25)                            # from elsewhere (a settings file): shown as is
    assert weights.currentText() == "650" and spin.value() == 125


def test_last_build_report(dialog, controller):
    assert dialog.report_text.isReadOnly() and dialog.report_text.toPlainText() == NO_BUILD_TEXT == "No build yet."
    report = ForgeReport([MaterialReport("Fixture A Regular", 5, ["latin"])], 5, 6, ["Glyph names were dropped."],
                         "C:/out/Fixture.ttf")
    controller.report = report
    controller.changed.emit()
    text = dialog.report_text.toPlainText()
    assert text == report.as_text()
    assert "Fixture A Regular: 5 characters" in text and "Glyph names were dropped." in text
    controller.report = None
    controller.error_detail = "Couldn't read B.otf\nTraceback: …"
    controller.changed.emit()
    assert dialog.report_text.toPlainText() == "Couldn't read B.otf\nTraceback: …"
    controller.error_detail = None
    controller.changed.emit()
    assert dialog.report_text.toPlainText() == NO_BUILD_TEXT


def test_set_locked_disables_what_changes_the_font(dialog):
    dialog.set_locked(True)
    controls = [dialog.base_combo, dialog.default_weight_combo, dialog.default_scale_spin]
    controls += [dialog.supplier_combo(g) for g in dialog.table_groups()]
    assert all(not w.isEnabled() for w in controls)
    dialog.show_all_button.click()                           # rebuilt while locked: still locked
    assert all(not dialog.supplier_combo(g).isEnabled() for g in ["latin", "han", "cjk_symbols"])
    assert dialog.report_text.isEnabled()                    # the report can still be read and copied
    dialog.set_locked(False)
    assert dialog.base_combo.isEnabled() and dialog.default_scale_spin.isEnabled()
    assert dialog.supplier_combo("han").isEnabled()


def test_apply_theme(dialog):
    assert LIGHT.window in dialog.styleSheet()
    dialog.show_all_button.click()
    assert dialog.table.item(dialog.table_groups().index("arabic"), COL_DRAWN_BY).foreground().color().name() \
        == LIGHT.muted
    dialog.apply_theme(DARK)
    assert DARK.window in dialog.styleSheet() and LIGHT.window not in dialog.styleSheet()
    assert dialog.table.item(dialog.table_groups().index("arabic"), COL_DRAWN_BY).foreground().color().name() \
        == DARK.muted
    assert dialog.supplier_combo("han") is not None
