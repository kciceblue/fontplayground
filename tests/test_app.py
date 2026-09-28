"""The mixer window end to end: scanning, choosing fonts through the picker, trying them in the preview, installing
with a fake installer, Start over, Advanced, theme, preferences, restore and closing."""
import json
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from fontplayground.catalog import scanner
from fontplayground.ui import build as build_module
from fontplayground.ui import model as model_module
from fontplayground.ui import workers
from fontplayground.ui.app import (PICKER, QUIT_QUESTION, RECIPE, MainWindow, preview_preferences,
                                   theme_preference, trial_text)
from fontplayground.ui.build import BuildState
from fontplayground.ui.requests import PickRequest
from fontplayground.ui.theme import DARK, LIGHT
from tests.fakes import FakeInstaller, copying_forge, waiting_forge
from tests.fixtures import build_font, cps

BASIC = set(range(0x20, 0x7F))
KANA = set(range(0x3041, 0x3097)) | set(range(0x30A1, 0x30FB))
HAN = set(range(0x4E00, 0x4E00 + 2600)) | cps("们这说国门来你好世界，。！、")
SAMPLE = "Hello 你好 あ"


@pytest.fixture(scope="module")
def mix_dir(tmp_path_factory):
    """Three fonts big enough for the picker's language filters: Latin, Chinese + Japanese, Korean."""
    d = tmp_path_factory.mktemp("mixfonts")
    build_font(d / "LatinSans.ttf", "Latin Sans", "Regular", BASIC | set(range(0xA0, 0x180)))
    build_font(d / "HanSans.ttf", "Han Sans", "Regular", BASIC | HAN | KANA)
    build_font(d / "HangulSans.ttf", "Hangul Sans", "Regular", BASIC | set(range(0xAC00, 0xAC00 + 2100)))
    return d


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(model_module, "RESULT_DIR", tmp_path / "results")
    monkeypatch.setattr(build_module, "STAGE_DIR", tmp_path / "stage")


@pytest.fixture
def installer(tmp_path):
    return FakeInstaller(tmp_path)


def _open(qtbot, font_dir, cfg, installer=None, sample=SAMPLE) -> MainWindow:
    w = MainWindow([font_dir], cfg, installer=installer or FakeInstaller(cfg))
    qtbot.addWidget(w)
    w.resize(1280, 820)
    w.show()
    with qtbot.waitSignal(w.scan_worker.finished_scan, timeout=30000):
        pass
    if sample is not None:
        w.model.set_sample_text(sample)
    return w


def _face(w, family):
    return next(f for f in w.picker.faces_by_key().values() if f.family == family)


def _choose(qtbot, w, family) -> None:
    """In the open picker, search for the family and press Enter (the user's way)."""
    assert w.picker_is_open()
    w.picker.search.setText(family)
    qtbot.waitUntil(lambda: w.picker.current_face() is not None and w.picker.current_face().family == family)
    qtbot.keyClick(w.picker.search, Qt.Key.Key_Return)


def _close(w) -> None:
    if w.model.is_busy():
        w.model.cancel(wait_ms=15000)
    if w.model.worker is not None:
        w.model.worker.wait(15000)
    w.model.discard_result()


@pytest.fixture
def slow_reads(monkeypatch):
    real = scanner.read_faces

    def slow(path):
        time.sleep(0.05)
        return real(path)
    monkeypatch.setattr(scanner, "read_faces", slow)


# ----- helpers -------------------------------------------------------------------------------------------
def test_preference_helpers_fall_back_to_defaults():
    assert theme_preference({}) == "system" and theme_preference({"theme": "dark"}) == "dark"
    assert theme_preference({"theme": "sepia"}) == "system"
    assert preview_preferences({}) == (30, False)
    assert preview_preferences({"preview_size": 40, "colour_by_font": True}) == (40, True)
    assert preview_preferences({"preview_size": 400, "colour_by_font": "yes"}) == (30, False)
    assert preview_preferences({"preview_size": True}) == (30, False)


def test_trial_text_says_what_is_being_tried():
    assert trial_text("Han Sans", "chinese_s", None, False).startswith("Trying Han Sans for Chinese — ")
    assert trial_text("Han Sans", "latin", None, True).startswith("Trying Han Sans as your main font")
    assert trial_text("Han Sans", "chinese_s", "Old Sans", False).startswith("Trying Han Sans instead of Old Sans")
    assert trial_text("Han Sans", "any", None, False).startswith("Trying Han Sans — ")


# ----- the flow ------------------------------------------------------------------------------------------
def test_starts_empty_and_scans_into_the_picker_catalog(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    assert w.left.currentIndex() == RECIPE and not w.recipe.cards
    assert len(w.picker.faces_by_key()) == 3 and len(w.model.catalog) == 3
    assert (tmp_path / "cfg" / "catalog.json").exists()
    assert not w.bar.primary_button.isEnabled()          # nothing to build yet
    assert w.pane.menu_button.menu() is w.menu


def test_main_font_then_the_prompt_then_a_chinese_font(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    w.recipe.choose_main_button.click()
    assert w.picker_is_open() and w.picker.language() == "latin"
    _choose(qtbot, w, "Latin Sans")
    assert not w.picker_is_open() and [r.face.family for r in w.model.rows] == ["Latin Sans"]
    assert all(k is None for k in w.model.pins.values())     # the main font is not pinned to anything
    # the sample has Chinese and Japanese Latin Sans cannot draw: the prompt offers the next step
    assert not w.recipe.prompt.isHidden()
    w.recipe.prompt_button.click()
    assert w.picker_is_open() and w.picker.language() == "chinese_s"
    _choose(qtbot, w, "Han Sans")
    han = _face(w, "Han Sans")
    assert [r.face.family for r in w.model.rows] == ["Latin Sans", "Han Sans"]
    assert w.model.pins["han"] == han.key
    assert w.pane.preview.missing_characters() == []
    assert w.bar.primary_button.isEnabled() and w.bar.primary_button.text() == "Install"


def test_the_preview_tries_the_current_font_and_forgets_it_on_cancel(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    w.model.add(_face(w, "Latin Sans"))
    w.open_picker(PickRequest("korean"))
    assert "안녕" in w.model.sample_text                     # a Korean line so trying Korean fonts shows something
    w.picker.search.setText("Hangul")
    qtbot.waitUntil(lambda: not w.pane.banner.isHidden(), timeout=3000)
    assert w.pane.banner_label.text().startswith("Trying Hangul Sans for Korean")
    assert len(w.pane.preview.shown_mix().fonts) == 2 and len(w.model.rows) == 1
    qtbot.keyClick(w.picker.search, Qt.Key.Key_Escape)
    assert not w.picker_is_open() and w.pane.banner.isHidden()
    assert len(w.pane.preview.shown_mix().fonts) == 1 and len(w.model.rows) == 1


def test_change_replaces_a_font_in_place(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    w.model.add(_face(w, "Latin Sans"))
    w.model.add(_face(w, "Hangul Sans"), "korean")
    w.recipe.cards[1].change_link.click()
    assert w.picker_is_open()
    w.picker.language_combo.setCurrentIndex(w.picker.language_combo.findData("chinese_s"))
    _choose(qtbot, w, "Han Sans")
    assert [r.face.family for r in w.model.rows] == ["Latin Sans", "Han Sans"]
    assert w.model.pins["hangul"] == _face(w, "Han Sans").key   # the pin followed the font it was on


def test_install_end_to_end_then_update(qtbot, mix_dir, font_dir, tmp_path, monkeypatch, installer):
    calls = []
    monkeypatch.setattr(workers, "forge", copying_forge(font_dir, calls))   # the "built" font is fixture A
    w = _open(qtbot, mix_dir, tmp_path / "cfg", installer)
    try:
        w.model.add(_face(w, "Latin Sans"))
        w.model.add(_face(w, "Han Sans"), "chinese_s")
        w.bar.primary_button.click()
        qtbot.waitUntil(lambda: w.controller.state is BuildState.INSTALLED, timeout=10000)
        assert w.bar.primary_button.text() == "Installed ✓" and not w.bar.primary_button.isEnabled()
        assert installer.installs == [(f"{w.model.family}-Regular.ttf", f"{w.model.family} Regular", True)]
        assert w.pane.preview.highlighter.mode == "built"          # the preview shows the font that was built
        w.recipe.cards[1].size_spin.setValue(90)
        assert w.bar.primary_button.text() == "Update installed font"
        assert w.pane.preview.highlighter.mode == "mix"
    finally:
        _close(w)


def test_building_locks_the_recipe_and_closes_the_picker(qtbot, mix_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(workers, "forge", waiting_forge)
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    try:
        w.model.add(_face(w, "Latin Sans"))
        w.open_picker(PickRequest("chinese_s"))
        w.model.combine()
        assert not w.picker_is_open() and w.recipe.is_locked()
        w.open_picker(PickRequest("chinese_s"))
        assert not w.picker_is_open()                             # no picking while a build runs
        w.controller.cancel()
        qtbot.waitUntil(lambda: not w.model.is_busy(), timeout=10000)
        assert not w.recipe.is_locked()
    finally:
        _close(w)


def test_start_over_clears_the_recipe(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    w.model.add(_face(w, "Latin Sans"))
    w.open_picker(PickRequest("korean"))
    w.start_over_action.trigger()
    assert not w.model.rows and not w.recipe.cards and not w.picker_is_open()
    assert w.controller.state is BuildState.IDLE


def test_advanced_opens_one_dialog(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    w.advanced_action.trigger()
    first = w.advanced
    assert first is not None and first.isVisible()
    w.recipe.advanced_link.click()
    assert w.advanced is first


def test_theme_choice_retints_every_part_and_persists(qtbot, mix_dir, tmp_path):
    cfg = tmp_path / "cfg"
    w = _open(qtbot, mix_dir, cfg)
    w.show_advanced()
    w.theme_actions["dark"].trigger()
    assert w.theme_manager.theme is DARK
    for widget in (w.pane, w.bar, w.recipe, w.picker, w.advanced):
        assert DARK.surface in widget.styleSheet() or DARK.window in widget.styleSheet() or \
            DARK.muted in widget.styleSheet(), type(widget).__name__
    assert json.loads((cfg / "settings.json").read_text(encoding="utf-8"))["theme"] == "dark"
    w.theme_actions["light"].trigger()
    assert w.theme_manager.theme is LIGHT and LIGHT.surface in w.pane.styleSheet()


def test_preview_preferences_persist(qtbot, mix_dir, tmp_path):
    cfg = tmp_path / "cfg"
    w = _open(qtbot, mix_dir, cfg)
    w.pane.size_slider.setValue(44)
    w.pane.colour_button.click()
    w.close()
    settings = json.loads((cfg / "settings.json").read_text(encoding="utf-8"))
    assert settings["preview_size"] == 44 and settings["colour_by_font"] is True
    again = _open(qtbot, mix_dir, cfg)
    assert again.pane.size_slider.value() == 44 and again.pane.colour_button.isChecked()
    assert again.pane.preview.point_size() == 44 and again.pane.preview.colour_by_font()


def test_the_recipe_is_restored_after_the_scan(qtbot, mix_dir, tmp_path):
    cfg = tmp_path / "cfg"
    w = _open(qtbot, mix_dir, cfg)
    w.model.add(_face(w, "Latin Sans"))
    w.model.add(_face(w, "Han Sans"), "chinese_s")
    w.model.set_sample_text("mine 你好")
    w.close()
    again = _open(qtbot, mix_dir, cfg, sample=None)
    assert [r.face.family for r in again.model.rows] == ["Latin Sans", "Han Sans"]
    assert again.model.pins["han"] == _face(again, "Han Sans").key
    assert again.model.sample_text == "mine 你好" and len(again.recipe.cards) == 2


def test_closing_during_a_scan_keeps_the_stored_recipe(qtbot, mix_dir, tmp_path, slow_reads):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    stored = json.dumps({"materials": [{"path": str(mix_dir / "LatinSans.ttf"), "index": 0}],
                         "family_name": "Kept", "names_edited": {"family": True}})
    (cfg / "forge_last.json").write_text(stored, encoding="utf-8")
    w = MainWindow([mix_dir], cfg, installer=FakeInstaller(cfg))
    qtbot.addWidget(w)
    w.close()
    assert (cfg / "forge_last.json").read_text(encoding="utf-8") == stored


def test_malformed_settings_do_not_break_startup(qtbot, mix_dir, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "settings.json").write_text("[1, 2", encoding="utf-8")
    (cfg / "forge_last.json").write_text('{"materials": "nope", "pins": 7}', encoding="utf-8")
    w = _open(qtbot, mix_dir, cfg)
    assert not w.model.rows and w.left.currentIndex() == RECIPE


def test_close_while_building_asks_first(qtbot, mix_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(workers, "forge", waiting_forge)
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    asked = []
    try:
        w.model.add(_face(w, "Latin Sans"))
        w.model.combine()
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No)
        assert not w.close() and w.model.is_busy() and asked == [QUIT_QUESTION]
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        assert w.close()
        qtbot.waitUntil(lambda: not w.model.is_busy(), timeout=10000)   # the cancel arrives as a queued signal
    finally:
        _close(w)


def test_rescan_keeps_the_recipe(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    w.model.add(_face(w, "Latin Sans"))
    w.rescan_action.trigger()
    with qtbot.waitSignal(w.scan_worker.finished_scan, timeout=30000):
        pass
    assert [r.face.family for r in w.model.rows] == ["Latin Sans"] and len(w.picker.faces_by_key()) == 3


def test_the_menu_has_every_action(qtbot, mix_dir, tmp_path):
    w = _open(qtbot, mix_dir, tmp_path / "cfg")
    texts = [a.text() for a in w.menu.actions() if not a.isSeparator()]
    assert texts == ["Rescan fonts", "Add folder…", "Start over", "Advanced…", "Theme", "Open settings folder"]
    assert [a.text() for a in w.theme_menu.actions()] == ["System", "Light", "Dark"]
