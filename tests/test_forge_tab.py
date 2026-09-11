import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeSpec, MaterialSpec
from fontplayground.ui.forge_tab import ForgeTab
from fontplayground.ui.preview import PreviewWidget, font_loader
from tests.fixtures import cps, fake_face


@pytest.fixture
def ab(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    return a, b


@pytest.fixture
def tab(qtbot):
    t = ForgeTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(t)
    return t


def _cleanup_result(tab: ForgeTab) -> None:
    # discard_result() unloads the font and deletes the temp file, ignoring errors: Qt's offscreen
    # font database on Windows keeps the file mapped, so the unlink may fail there. Best effort only.
    path = tab.result_path
    tab.discard_result()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# 1 ---------------------------------------------------------------------------
def test_set_materials_builds_rows_and_weight_edits_reach_spec(tab, ab):
    a, b = ab
    tab.set_materials([a, b])
    assert tab.table.rowCount() == 2
    assert [r.face for r in tab.rows()] == [a, b]
    spec = tab.build_spec()
    assert [m.face for m in spec.materials] == [a, b]
    assert spec.base_index == 0
    assert tab.base_radio(0).isChecked() and not tab.base_radio(1).isChecked()
    assert tab.table.item(1, 1).text() == "Fixture B Bold"
    assert "static font" in tab.table.item(0, 5).text()

    tab.weight_spin(1).setValue(500)
    assert tab.build_spec().materials[1].weight == 500
    assert tab.build_spec().materials[0].weight is None
    tab.scale_spin(0).setValue(120)
    assert tab.build_spec().materials[0].scale == pytest.approx(1.2)


# 2 ---------------------------------------------------------------------------
def test_move_up_reorders_and_rules_follow_the_face(tab, ab):
    a, b = ab
    tab.set_materials([a, b])
    han = tab.rule_combo("han")
    assert [han.itemText(i) for i in range(han.count())] == [
        "Auto (priority order)", "1. Fixture A Regular", "2. Fixture B Bold"]
    han.setCurrentIndex(2)  # B
    assert tab.build_spec().script_rules["han"] == 1

    tab.base_radio(1).setChecked(True)  # base follows the face too
    tab.table.selectRow(1)
    tab.up_button.click()
    assert [r.face for r in tab.rows()] == [b, a]
    spec = tab.build_spec()
    assert spec.script_rules["han"] == 0
    assert spec.base_index == 0
    assert tab.rule_combo("han").currentText() == "1. Fixture B Bold"
    assert tab.table.currentRow() == 0

    tab.down_button.click()
    assert [r.face for r in tab.rows()] == [a, b]
    assert tab.build_spec().script_rules["han"] == 1
    assert tab.build_spec().base_index == 1


# 3 ---------------------------------------------------------------------------
def test_set_materials_keeps_existing_rows_and_settings_round_trip(qtbot, tab, ab, tmp_path):
    a, b = ab
    tab.set_materials([a, b])
    tab.weight_spin(0).setValue(300)
    tab.weight_spin(1).setValue(500)
    tab.set_materials([b])
    assert [r.face for r in tab.rows()] == [b]
    assert tab.rows()[0].weight == 500

    tab.set_materials([b, a])
    assert [r.face for r in tab.rows()] == [b, a]
    assert [r.weight for r in tab.rows()] == [500, None]
    tab.weight_spin(1).setValue(300)
    tab.scale_spin(0).setValue(80)
    tab.base_radio(1).setChecked(True)
    tab.rule_combo("han").setCurrentIndex(1)     # B
    tab.rule_combo("latin").setCurrentIndex(2)   # A
    tab.family_edit.setText("Fam")
    tab.style_edit.setText("Heavy")
    tab.default_weight_combo.setCurrentIndex(tab.default_weight_combo.findText("700"))
    tab.default_scale_spin.setValue(90)
    output = str(tmp_path / "out" / "Fam.ttf")
    tab.output_edit.setText(output)

    spec = tab.build_spec()
    assert [m.face for m in spec.materials] == [b, a]
    assert [(m.weight, m.scale) for m in spec.materials] == [(500, 0.8), (300, None)]
    assert spec.base_index == 1
    assert spec.script_rules["han"] == 0 and spec.script_rules["latin"] == 1
    assert (spec.default_weight, spec.default_scale) == (700, pytest.approx(0.9))
    assert (spec.family_name, spec.style_name) == ("Fam", "Heavy")

    d = tab.to_settings()
    assert d["output_path"] == output

    other = ForgeTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(other)
    other.from_settings(d, {a.key: a, b.key: b})
    assert other.build_spec() == spec
    assert other.output_edit.text() == output
    assert other.rule_combo("han").currentText() == "1. Fixture B Bold"
    assert other.base_radio(1).isChecked()
    assert other.weight_spin(0).value() == 500 and other.weight_spin(1).value() == 300

    third = ForgeTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(third)
    third.apply_spec(spec)
    assert third.build_spec() == spec

    # a saved material that no longer exists is dropped, and indices are remapped
    fourth = ForgeTab(PreviewWidget(sizes=(12,)))
    qtbot.addWidget(fourth)
    fourth.from_settings(d, {a.key: a})
    s = fourth.build_spec()
    assert [m.face for m in s.materials] == [a] and s.base_index == 0
    assert s.script_rules["han"] is None and s.script_rules["latin"] == 0


# 4 ---------------------------------------------------------------------------
def test_combine_end_to_end(qtbot, tab, ab, tmp_path):
    a, b = ab
    tab.set_materials([a, b])
    tab.family_edit.setText("Forged Test")
    tab.combine()
    assert tab.worker is not None
    assert not tab.combine_button.isEnabled()
    with qtbot.waitSignal(tab.worker.succeeded, timeout=60000):
        pass
    try:
        text = tab.report.toPlainText()
        assert "Characters: 7" in text
        assert "Sample characters not covered:" in text
        assert tab.result_path and os.path.exists(tab.result_path)
        assert Path(tab.result_path).parent.name == "fontplayground"
        assert tab.preview.current_family() == "Forged Test"
        assert tab.combine_button.isEnabled() and tab.save_button.isEnabled()
        assert tab.progress_bar.isHidden() and tab.stage_label.isHidden()

        out = tmp_path / "saved" / "out.ttf"
        tab.save_to(str(out))
        assert out.is_file() and out.stat().st_size == Path(tab.result_path).stat().st_size
        assert read_faces(out)[0].family == "Forged Test"
    finally:
        _cleanup_result(tab)
    assert tab.result_path is None and not tab.save_button.isEnabled()


# 5 ---------------------------------------------------------------------------
def test_combine_without_materials_warns_and_starts_no_worker(tab, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kw: calls.append(args))
    tab.combine()
    assert tab.worker is None
    assert len(calls) == 1
    assert "Add at least one material." in calls[0][2]
    assert tab.combine_button.isEnabled()


# extras ----------------------------------------------------------------------
def test_remove_emits_material_removed_and_clears_its_rule(qtbot, tab, ab):
    a, b = ab
    tab.set_materials([a, b])
    tab.rule_combo("han").setCurrentIndex(2)  # B
    tab.table.selectRow(1)
    with qtbot.waitSignal(tab.materialRemoved) as blocker:
        with qtbot.waitSignal(tab.settingsChanged):
            tab.remove_button.click()
    assert blocker.args == [b.key]
    assert [r.face for r in tab.rows()] == [a]
    assert tab.build_spec().script_rules["han"] is None
    assert tab.rule_combo("han").count() == 2


def test_edits_emit_settings_changed(qtbot, tab, ab):
    a, b = ab
    with qtbot.waitSignal(tab.settingsChanged):
        tab.set_materials([a, b])
    with qtbot.assertNotEmitted(tab.settingsChanged):
        tab.set_materials([a, b])  # nothing changed
    with qtbot.waitSignal(tab.settingsChanged):
        tab.weight_spin(0).setValue(700)
    with qtbot.waitSignal(tab.settingsChanged):
        tab.base_radio(1).setChecked(True)
    with qtbot.waitSignal(tab.settingsChanged):
        tab.rule_combo("kana").setCurrentIndex(1)
    with qtbot.waitSignal(tab.settingsChanged):
        tab.family_edit.setText("X")
    with qtbot.waitSignal(tab.settingsChanged):
        tab.output_edit.setText("y.ttf")


def test_save_to_without_result_raises(tab, tmp_path):
    with pytest.raises(RuntimeError, match="Nothing to save"):
        tab.save_to(str(tmp_path / "out.ttf"))


def test_combine_failure_reports_and_shows_critical(qtbot, tab, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kw: calls.append(args))
    ghost = fake_face(cps("ab"), path=str(tmp_path / "missing.ttf"), family="Ghost")
    tab.set_materials([ghost])
    tab.combine()
    with qtbot.waitSignal(tab.worker.failed, timeout=60000):
        pass
    assert tab.report.toPlainText().startswith("Combine failed:\n")
    assert len(calls) == 1 and calls[0][1] == "Combine failed"
    assert "\n" not in calls[0][2]
    assert tab.result_path is None and not tab.save_button.isEnabled()
    assert tab.combine_button.isEnabled()


def test_apply_spec_from_spec_object(tab, ab):
    a, b = ab
    spec = ForgeSpec(materials=[MaterialSpec(b, 500, None), MaterialSpec(a, None, 1.5)], base_index=1,
                     script_rules={"han": 0, "latin": None}, default_weight=400, default_scale=1.1,
                     family_name="Applied", style_name="Italic")
    tab.apply_spec(spec)
    got = tab.build_spec()
    assert got.materials == spec.materials and got.base_index == 1
    assert got.script_rules["han"] == 0 and got.script_rules["latin"] is None
    assert got.default_weight == 400 and got.default_scale == pytest.approx(1.1)
    assert (got.family_name, got.style_name) == ("Applied", "Italic")
    assert tab.scale_spin(1).value() == 150 and tab.scale_spin(0).text() == "default"
