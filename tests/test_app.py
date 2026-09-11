import json
import os
import shutil
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from fontplayground.catalog import scanner
from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError
from fontplayground.ui import forge_tab as forge_tab_module
from fontplayground.ui import workers
from fontplayground.ui.app import QUIT_QUESTION, MainWindow


def _open(qtbot, font_dir, cfg):
    w = MainWindow([font_dir], cfg)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.scan_worker.finished_scan, timeout=30000):
        pass
    return w


def _face_item(w, face):
    tree = w.fonts_tab.tree
    for i in range(tree.topLevelItemCount()):
        fam = tree.topLevelItem(i)
        for j in range(fam.childCount()):
            child = fam.child(j)
            if child.data(0, Qt.ItemDataRole.UserRole) == face.key:
                return child
    raise AssertionError(f"no row for {face.key}")


def _cleanup_result(w) -> None:
    # Best effort: Qt's offscreen font database on Windows may keep a loaded result mapped, so unlink can fail.
    path = w.forge_tab.result_path
    w.forge_tab.discard_result()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def slow_reads(monkeypatch):
    """Make every font read take 50 ms, so a scan of the fixture folder is still running after MainWindow()."""
    real = scanner.read_faces

    def slow(path):
        time.sleep(0.05)
        return real(path)
    monkeypatch.setattr(scanner, "read_faces", slow)


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


def test_scan_populates_fonts_and_cache(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    assert len(w.fonts_tab.faces_by_key()) == 7
    assert (tmp_path / "cfg" / "catalog.json").exists()


def test_ticking_feeds_forge_and_persists(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _face_item(w, a).setCheckState(0, Qt.CheckState.Checked)
    assert len(w.forge_tab.rows()) == 1
    saved = json.loads((tmp_path / "cfg" / "forge_last.json").read_text(encoding="utf-8"))
    assert len(saved["materials"]) == 1 and saved["materials"][0]["path"] == a.path


def test_forge_settings_are_restored(qtbot, font_dir, tmp_path):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "forge_last.json").write_text(json.dumps({
        "materials": [{"path": b.path, "index": 0, "weight": 500, "scale": None},
                      {"path": a.path, "index": 0, "weight": None, "scale": None}],
        "base_index": 1, "script_rules": {"han": 0}, "default_weight": None, "default_scale": 1.0,
        "family_name": "Restored", "style_name": "Regular", "output_path": str(tmp_path / "r.ttf"),
    }), encoding="utf-8")
    w = _open(qtbot, font_dir, cfg)
    spec = w.forge_tab.build_spec()
    assert [m.face.key for m in spec.materials] == [b.key, a.key]
    assert spec.materials[0].weight == 500 and spec.base_index == 1
    assert spec.script_rules["han"] == 0 and spec.family_name == "Restored"
    assert w.fonts_tab.selected_faces() and {f.key for f in w.fonts_tab.selected_faces()} == {a.key, b.key}


def test_closing_during_scan_keeps_forge_settings(qtbot, font_dir, tmp_path, slow_reads):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    # Written compactly (the app writes indented JSON), so any rewrite at all shows up as a difference.
    original = json.dumps({
        "materials": [{"path": b.path, "index": 0, "weight": 500, "scale": None},
                      {"path": a.path, "index": 0, "weight": None, "scale": None}],
        "base_index": 1, "script_rules": {"han": 0}, "default_weight": None, "default_scale": 1.0,
        "family_name": "Kept", "style_name": "Regular", "output_path": str(tmp_path / "k.ttf"),
    })
    (cfg / "forge_last.json").write_text(original, encoding="utf-8")
    w = MainWindow([font_dir], cfg)
    qtbot.addWidget(w)
    worker = w.scan_worker
    assert worker.isRunning()
    assert w.close() is True
    assert worker.interrupted and not worker.isRunning()
    qtbot.wait(200)  # deliver the partial finished_scan that the interrupted worker emitted on its way out
    assert (cfg / "forge_last.json").read_text(encoding="utf-8") == original
    assert w.forge_tab.rows() == [] and w.fonts_tab.selected_faces() == []


def test_scan_requests_during_a_scan_run_once_it_is_done(qtbot, font_dir, tmp_path, monkeypatch, slow_reads):
    extra = tmp_path / "extra"
    extra.mkdir()
    shutil.copy(font_dir / "A.ttf", extra / "E.ttf")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kw: str(extra))
    w = MainWindow([font_dir], tmp_path / "cfg")
    qtbot.addWidget(w)
    first = w.scan_worker
    assert first.isRunning()
    assert not w.fonts_tab.rescan_button.isEnabled() and not w.fonts_tab.add_folder_button.isEnabled()
    w.add_folder()                   # both of these used to be dropped while a scan was running
    w.start_scan(use_cache=False)    # (what the Rescan button does)
    assert w.scan_worker is first
    with qtbot.waitSignal(first.finished_scan, timeout=30000):
        pass
    second = w.scan_worker
    assert second is not first and second.isRunning()
    assert second.use_cache is False and extra in second.dirs
    qtbot.waitUntil(lambda: w.fonts_tab.progress.isHidden(), timeout=30000)
    assert w.scan_worker is second and not second.isRunning()
    assert len(w.fonts_tab.faces_by_key()) == 8
    assert w.fonts_tab.rescan_button.isEnabled() and w.fonts_tab.add_folder_button.isEnabled()
    saved = json.loads((tmp_path / "cfg" / "settings.json").read_text(encoding="utf-8"))
    assert saved["extra_dirs"] == [str(extra)]


def test_sample_text_is_shared_between_tabs(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    w.fonts_preview.editor.setPlainText("shared sample")
    assert w.forge_preview.sample_text() == "shared sample"
    w.forge_preview.editor.setPlainText("back again")
    assert w.fonts_preview.sample_text() == "back again"


def test_forge_validation_error_is_shown_in_the_status_bar(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    assert w.statusBar().currentMessage() == "7 font faces found"
    assert not w.forge_tab.combine_button.isEnabled()
    (a,) = read_faces(font_dir / "A.ttf")
    _face_item(w, a).setCheckState(0, Qt.CheckState.Checked)
    assert w.forge_tab.combine_button.isEnabled()
    assert w.statusBar().currentMessage() == "7 font faces found"  # a valid spec does not wipe other messages
    w.forge_tab.family_edit.setText("")
    assert not w.forge_tab.combine_button.isEnabled()
    assert w.statusBar().currentMessage() == "Family name is empty."
    w.forge_tab.family_edit.setText("Back")
    assert w.forge_tab.combine_button.isEnabled()
    assert w.statusBar().currentMessage() == ""


def test_combine_disables_the_font_tree_until_it_is_done(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _face_item(w, a).setCheckState(0, Qt.CheckState.Checked)
    w.forge_tab.combine()
    assert not w.fonts_tab.tree.isEnabled()
    qtbot.waitUntil(lambda: w.fonts_tab.tree.isEnabled(), timeout=60000)
    try:
        assert w.forge_tab.result_path and os.path.exists(w.forge_tab.result_path)
    finally:
        _cleanup_result(w)


def test_close_during_combine_asks_and_cancels(qtbot, font_dir, tmp_path, monkeypatch, forge_waits_for_cancel):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _face_item(w, a).setCheckState(0, Qt.CheckState.Checked)
    w.forge_tab.combine()
    worker = w.forge_tab.worker
    assert worker.isRunning() and not w.fonts_tab.tree.isEnabled()

    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args, **kw: asked.append(args[2]) or QMessageBox.StandardButton.No)
    assert w.close() is False
    assert asked == [QUIT_QUESTION]
    assert worker.isRunning() and not worker.is_cancelled()

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kw: QMessageBox.StandardButton.Yes)
    assert w.close() is True
    assert worker.is_cancelled() and not worker.isRunning()
    # the queued `cancelled` lands afterwards without any dialog (a modal one would hang here)
    qtbot.waitUntil(lambda: w.fonts_tab.tree.isEnabled(), timeout=5000)
    assert w.forge_tab.report.toPlainText() == "Combine cancelled."


def test_stale_results_are_removed_on_start_and_the_result_on_close(qtbot, font_dir, tmp_path):
    forge_tab_module.RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stale = forge_tab_module.RESULT_DIR / "forged-stale0000.ttf"
    stale.write_bytes(b"stale")
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    assert not stale.exists()

    result = tmp_path / "forged-result.ttf"
    result.write_bytes(b"result")
    w.forge_tab.result_path = str(result)
    w.forge_tab.save_button.setEnabled(True)
    assert w.close() is True
    assert w.forge_tab.result_path is None and not result.exists()
    assert not w.forge_tab.save_button.isEnabled()
