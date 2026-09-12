import json
import os
import shutil
import time

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from fontplayground.catalog import scanner
from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError
from fontplayground.ui import workers
from fontplayground.ui.app import CHECK, FORGE, PICK, QUIT_QUESTION, MainWindow


def _open(qtbot, font_dir, cfg):
    w = MainWindow([font_dir], cfg)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.scan_worker.finished_scan, timeout=30000):
        pass
    return w


def _add(w, face):
    """Add a face the way the user does: select it on the Pick page and press the big button."""
    w.pick_page.select_face(face.key)
    w.pick_page.add_button.click()


def _cleanup_result(w) -> None:
    path = w.model.result_path
    w.model.discard_result()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def slow_reads(monkeypatch):
    real = scanner.read_faces

    def slow(path):
        time.sleep(0.05)
        return real(path)
    monkeypatch.setattr(scanner, "read_faces", slow)


@pytest.fixture
def forge_waits_for_cancel(monkeypatch):
    def fake_forge(spec, output_path, progress=None):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            progress("waiting", 0.0)
            time.sleep(0.01)
        raise ForgeError("test", None, "never cancelled")
    monkeypatch.setattr(workers, "forge", fake_forge)


def test_scan_populates_catalog_and_cache(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    assert len(w.pick_page.faces_by_key()) == 7 and len(w.model.catalog) == 7
    assert (tmp_path / "cfg" / "catalog.json").exists()
    assert w.step() == PICK and not w.rail.is_reachable(CHECK)
    assert not w.tray.primary_button.isEnabled()


def test_adding_a_font_unlocks_check_and_persists(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    assert [r.face.key for r in w.model.rows] == [a.key]
    assert w.rail.is_reachable(CHECK) and w.tray.primary_button.isEnabled()
    assert w.tray.primary_button.text() == "Next: Check ›"
    w._save_timer.stop()
    w.save_forge_settings()
    saved = json.loads((tmp_path / "cfg" / "forge_last.json").read_text(encoding="utf-8"))
    assert saved["materials"][0]["path"] == a.path


def test_navigation_through_the_steps(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    _add(w, a)
    _add(w, b)
    w.tray.primary_button.click()
    assert w.step() == CHECK and w.tray.primary_button.text() == "Next: Forge ›"
    assert w.tray.back_button.isVisible() or not w.tray.back_button.isHidden()
    w.tray.back_button.click()
    assert w.step() == PICK
    w.go(CHECK)
    w.tray.primary_button.click()
    assert w.step() == FORGE and w.model.is_busy()  # the forge starts on arrival
    with qtbot.waitSignal(w.model.resultReady, timeout=60000):
        pass
    try:
        assert w.tray.primary_button.text().startswith("Save to")
        w.model.set_output(str(tmp_path / "out.ttf"), by_user=True)
        w.tray.primary_button.click()
        assert (tmp_path / "out.ttf").exists()
        assert w.tray.primary_button.text() == "Saved ✓"
    finally:
        _cleanup_result(w)


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
        "pins": {"latin": [a.path, 0]}, "names_edited": {"family": True, "style": False, "output": True},
        "sample_text": "abc",
    }), encoding="utf-8")
    w = _open(qtbot, font_dir, cfg)
    spec = w.model.build_spec()
    assert [m.face.key for m in spec.materials] == [b.key, a.key]
    assert spec.materials[0].weight == 500 and spec.base_index == 1
    assert spec.script_rules["latin"] == 1 and spec.family_name == "Restored"
    assert w.model.sample_text == "abc" and w.rail.is_reachable(FORGE)


def test_closing_during_scan_keeps_forge_settings(qtbot, font_dir, tmp_path, slow_reads):
    (a,) = read_faces(font_dir / "A.ttf")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    original = json.dumps({"materials": [{"path": a.path, "index": 0, "weight": None, "scale": None}],
                           "base_index": 0, "script_rules": {}, "default_weight": None, "default_scale": 1.0,
                           "family_name": "Kept", "style_name": "Regular", "output_path": str(tmp_path / "k.ttf")})
    (cfg / "forge_last.json").write_text(original, encoding="utf-8")
    w = MainWindow([font_dir], cfg)
    qtbot.addWidget(w)
    assert w.scan_worker.isRunning()
    assert w.close() is True
    qtbot.wait(200)
    assert (cfg / "forge_last.json").read_text(encoding="utf-8") == original
    assert w.model.rows == []


def test_scan_requests_during_a_scan_run_once_it_is_done(qtbot, font_dir, tmp_path, monkeypatch, slow_reads):
    extra = tmp_path / "extra"
    extra.mkdir()
    shutil.copy(font_dir / "A.ttf", extra / "E.ttf")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kw: str(extra))
    w = MainWindow([font_dir], tmp_path / "cfg")
    qtbot.addWidget(w)
    first = w.scan_worker
    assert first.isRunning() and not w.rail.rescan_action.isEnabled()
    w.add_folder()
    w.start_scan(use_cache=False)
    assert w.scan_worker is first
    with qtbot.waitSignal(first.finished_scan, timeout=30000):
        pass
    second = w.scan_worker
    assert second is not first and second.use_cache is False and extra in second.dirs
    qtbot.waitUntil(lambda: not second.isRunning() and w.rail.rescan_action.isEnabled(), timeout=30000)
    assert len(w.pick_page.faces_by_key()) == 8


def test_sample_text_is_shared_between_pages(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    w.previews[PICK].editor.setPlainText("shared sample")
    assert w.model.sample_text == "shared sample"
    assert w.previews[CHECK].sample_text() == "shared sample" and w.previews[FORGE].sample_text() == "shared sample"
    w.previews[FORGE].editor.setPlainText("back again")
    assert w.previews[PICK].sample_text() == "back again"


def test_start_over_clears_everything(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    w.go(CHECK)
    w.rail.start_over_action.trigger()
    assert w.model.rows == [] and w.step() == PICK and not w.rail.is_reachable(CHECK)


def test_close_during_forge_asks_and_cancels(qtbot, font_dir, tmp_path, monkeypatch, forge_waits_for_cancel):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    w.go(FORGE)
    assert w.model.is_busy()
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args, **kw: asked.append(args[2]) or QMessageBox.StandardButton.No)
    assert w.close() is False and asked == [QUIT_QUESTION] and w.model.is_busy()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kw: QMessageBox.StandardButton.Yes)
    with qtbot.waitSignal(w.model.resultCancelled, timeout=15000):
        assert w.close() is True
    assert not w.model.is_busy()


def test_status_bar_pluralises_unreadable_files(qtbot, font_dir, tmp_path):
    shutil.copytree(font_dir, tmp_path / "f")
    (tmp_path / "f" / "broken.ttf").write_bytes(b"not a font")
    w = _open(qtbot, tmp_path / "f", tmp_path / "cfg")
    assert w.statusBar().currentMessage() == "7 font faces found, 1 unreadable file skipped"


def test_search_box_has_focus_on_pick(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    w.show()
    w.go(PICK)
    assert w.pick_page.search.hasFocus() or w.focusWidget() is w.pick_page.search


def test_forge_locks_navigation_and_editing(qtbot, font_dir, tmp_path, forge_waits_for_cancel):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    w.go(FORGE)
    assert w.model.is_busy()
    assert not w.rail.buttons[PICK].isEnabled() and not w.rail.buttons[CHECK].isEnabled()
    assert not w.tray.back_button.isEnabled() and not w.pick_page.add_button.isEnabled()
    with qtbot.waitSignal(w.model.resultCancelled, timeout=15000):
        w.model.cancel()
    assert w.rail.buttons[PICK].isEnabled() and w.tray.back_button.isEnabled() and w.pick_page.add_button.isEnabled()


def test_start_over_forgets_names_and_edits(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    w.model.set_family("Typed Name", by_user=True)
    w.rail.start_over_action.trigger()
    assert w.model.rows == [] and w.model.family == "Forged" and not w.model.names_edited["family"]
    _add(w, a)
    assert w.model.family == "Fixture A Forged"


def test_malformed_settings_do_not_break_startup(qtbot, font_dir, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "forge_last.json").write_text('{"materials": "nonsense", "pins": {"latin": "x"}, "base_index": "zero"}',
                                         encoding="utf-8")
    w = _open(qtbot, font_dir, cfg)
    assert w.model.rows == [] and w.step() == PICK
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    assert w.rail.is_reachable(CHECK)


def test_primary_offers_choose_location_after_a_result(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _add(w, a)
    w.go(FORGE)
    with qtbot.waitSignal(w.model.resultReady, timeout=60000):
        pass
    try:
        assert w.tray.primary_button.text().startswith("Save to") or w.tray.primary_button.toolTip().startswith("Save to")
        assert not w.tray.primary_menu_button.isHidden()
        assert [a.text() for a in w._primary_menu.actions()] == ["Choose location…"]
    finally:
        _cleanup_result(w)
