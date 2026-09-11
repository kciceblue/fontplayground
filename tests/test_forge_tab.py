import os
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError, ForgeSpec, MaterialSpec
from fontplayground.ui import forge_tab as forge_tab_module
from fontplayground.ui import workers
from fontplayground.ui.forge_tab import COL_FONT, COL_NOTE, ForgeTab, clean_stale_results
from fontplayground.ui.preview import PreviewWidget
from fontplayground.ui.workers import CombineWorker
from tests.fixtures import cps, fake_face


@pytest.fixture
def forge_waits_for_cancel(monkeypatch):
    """Replace forge() with one that keeps reporting progress until the worker cancels it (or 10 s pass)."""
    def fake_forge(spec, output_path, progress=None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            progress("waiting", 0.0)  # raises ForgeError('cancelled') once cancel() has been called
            time.sleep(0.01)
        raise ForgeError("test", None, "never cancelled")
    monkeypatch.setattr(workers, "forge", fake_forge)


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
    busy: list[bool] = []
    tab.busyChanged.connect(busy.append)
    tab.combine()
    assert tab.worker is not None
    assert not tab.combine_button.isEnabled()
    # the inputs are frozen while it runs; the preview editor and the report stay usable
    assert busy == [True]
    assert not tab.materials_box.isEnabled() and not tab.rules_box.isEnabled() and not tab.defaults_box.isEnabled()
    assert tab.preview_box.isEnabled() and tab.preview.editor.isEnabled() and tab.report.isEnabled()
    with qtbot.waitSignal(tab.worker.succeeded, timeout=60000):
        pass
    try:
        text = tab.report.toPlainText()
        assert "Characters: 7" in text
        assert "Sample characters not covered:" in text
        assert tab.result_path and os.path.exists(tab.result_path)
        assert Path(tab.result_path).parent == forge_tab_module.RESULT_DIR
        assert tab.preview.current_family() == "Forged Test"
        assert busy == [True, False]
        assert tab.materials_box.isEnabled() and tab.rules_box.isEnabled() and tab.defaults_box.isEnabled()
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
    assert not tab.combine_button.isEnabled()  # the button is already off; combine() is the programmatic path
    tab.combine()
    assert tab.worker is None
    assert len(calls) == 1
    assert "Add at least one material." in calls[0][2]
    assert not tab.combine_button.isEnabled()
    assert tab.combine_button.toolTip() == "Add at least one material."


def test_combine_button_follows_validation(qtbot, tab, ab):
    a, b = ab
    messages: list[str] = []
    tab.statusMessage.connect(messages.append)
    assert not tab.combine_button.isEnabled()
    assert tab.validation_error() == "Add at least one material."

    tab.set_materials([a])
    assert tab.combine_button.isEnabled() and tab.combine_button.toolTip() == ""
    assert messages[-1] == "" and tab.validation_error() == ""

    tab.family_edit.setText("   ")
    assert not tab.combine_button.isEnabled()
    assert tab.combine_button.toolTip() == "Family name is empty." == messages[-1]
    tab.family_edit.setText("Forged")
    assert tab.combine_button.isEnabled() and messages[-1] == ""

    # set_materials re-checks even when the set of rows does not change, and reports unsupported faces
    bad = fake_face(cps("ab"), path="cff2.otf", family="Fixture Z", outline="CFF2")
    tab.set_materials([a, bad])
    assert not tab.combine_button.isEnabled()
    assert messages[-1] == "Fixture Z Regular: CFF2 outlines are not supported" == tab.combine_button.toolTip()
    del messages[:]
    tab.set_materials([a, bad])
    assert messages == ["Fixture Z Regular: CFF2 outlines are not supported"]

    # apply_spec re-checks too, in both directions
    tab.apply_spec(ForgeSpec(materials=[MaterialSpec(b)], family_name=""))
    assert not tab.combine_button.isEnabled() and messages[-1] == "Family name is empty."
    tab.apply_spec(ForgeSpec(materials=[MaterialSpec(b)]))
    assert tab.combine_button.isEnabled() and messages[-1] == ""

    # row edits: an out-of-range default scale
    tab.default_scale_spin.setValue(1000)
    tab.scale_spin(0).setValue(0)
    with qtbot.assertNotEmitted(tab.busyChanged):
        tab.default_weight_combo.setCurrentIndex(1)
    assert tab.combine_button.isEnabled()
    tab.style_edit.setText("")
    assert not tab.combine_button.isEnabled() and messages[-1] == "Style name is empty."


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
    assert not tab.materials_box.isEnabled()
    with qtbot.waitSignal(tab.worker.failed, timeout=60000):
        pass
    report = tab.report.toPlainText()
    assert report.startswith("Combine failed:\n[prepare (Ghost Regular)] ")
    assert "Traceback (most recent call last):" in report  # ForgeError carries the full traceback too
    assert len(calls) == 1 and calls[0][1] == "Combine failed"
    assert "\n" not in calls[0][2] and calls[0][2] == report.splitlines()[1]
    assert tab.result_path is None and not tab.save_button.isEnabled()
    assert tab.combine_button.isEnabled()
    assert tab.materials_box.isEnabled() and tab.rules_box.isEnabled() and tab.defaults_box.isEnabled()


def test_worker_cancel_stops_at_the_next_stage_boundary(qapp, ab, tmp_path):
    a, b = ab
    out = tmp_path / "cancelled.ttf"
    worker = CombineWorker(ForgeSpec(materials=[MaterialSpec(a), MaterialSpec(b)]), str(out))
    events: list[str] = []
    worker.progress.connect(lambda stage, fraction: events.append(f"progress:{stage}"))
    worker.succeeded.connect(lambda report: events.append("succeeded"))
    worker.failed.connect(lambda message: events.append(f"failed:{message}"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    assert not worker.is_cancelled()
    worker.cancel()
    assert worker.is_cancelled()
    worker.run()  # synchronously: forge() reports "plan" first, which is where the cancel lands
    assert events == ["cancelled"]
    assert not out.exists()

    # the same run without a cancel goes through to the end
    worker = CombineWorker(ForgeSpec(materials=[MaterialSpec(a), MaterialSpec(b)]), str(out))
    events.clear()
    worker.progress.connect(lambda stage, fraction: events.append(f"progress:{stage}"))
    worker.succeeded.connect(lambda report: events.append("succeeded"))
    worker.cancelled.connect(lambda: events.append("cancelled"))
    worker.run()
    assert events[0] == "progress:plan" and events[-1] == "succeeded" and "cancelled" not in events
    assert out.is_file()


def test_cancel_combine_reports_cancelled_without_a_dialog(qtbot, tab, ab, monkeypatch, forge_waits_for_cancel):
    a, b = ab
    dialogs = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kw: dialogs.append(args))
    assert tab.cancel_combine() is False  # nothing running
    tab.set_materials([a, b])
    busy: list[bool] = []
    tab.busyChanged.connect(busy.append)
    tab.combine()
    worker = tab.worker
    assert tab.is_busy() and busy == [True]
    out = Path(worker.output_path)
    out.write_bytes(b"partial")  # as if the cancel landed after "finish" wrote the file
    with qtbot.waitSignal(worker.cancelled, timeout=15000):
        assert tab.cancel_combine() is True
    assert worker.is_cancelled()
    qtbot.waitUntil(lambda: not tab.is_busy() and busy == [True, False], timeout=15000)
    assert tab.report.toPlainText() == "Combine cancelled."
    assert dialogs == []
    assert not out.exists()
    assert tab.result_path is None and not tab.save_button.isEnabled()
    assert tab.combine_button.isEnabled() and tab.materials_box.isEnabled()
    assert tab.progress_bar.isHidden() and tab.stage_label.isHidden()


def test_cancel_combine_can_block_until_the_worker_has_stopped(qtbot, tab, ab, forge_waits_for_cancel):
    a, b = ab
    tab.set_materials([a, b])
    tab.combine()
    worker = tab.worker
    assert worker.isRunning()
    assert tab.cancel_combine(wait_ms=15000) is True
    assert not worker.isRunning() and worker.is_cancelled()
    qtbot.waitUntil(lambda: not tab._busy, timeout=5000)  # the queued `cancelled` still lands afterwards


def test_material_cells_carry_tooltips_for_elided_text(tab, ab):
    a, b = ab
    restricted = fake_face(cps("ab"), path="r.ttf", family="Fixture R", style="Regular", embedding="restricted")
    tab.set_materials([a, restricted])
    for row, face in enumerate((a, restricted)):
        font_tip = tab.table.item(row, COL_FONT).toolTip()
        assert font_tip.splitlines() == [face.display_name, f"{face.path} (face {face.index})"]
        note = tab.table.item(row, COL_NOTE)
        assert note.toolTip() == note.text()
    assert "restricted licence" in tab.table.item(1, COL_NOTE).toolTip()


def test_clean_stale_results_removes_only_forged_files(tmp_path, monkeypatch):
    fake_dir = tmp_path / "fontplayground"
    monkeypatch.setattr(forge_tab_module, "RESULT_DIR", fake_dir)
    clean_stale_results()  # no folder yet: nothing to do, no error
    fake_dir.mkdir()
    stale = fake_dir / "forged-deadbeef.ttf"
    stale.write_bytes(b"x")
    other = fake_dir / "keep.txt"
    other.write_bytes(b"y")
    clean_stale_results()
    assert not stale.exists() and other.exists()


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
