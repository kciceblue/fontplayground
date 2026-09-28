"""ActionBar: names, status texts per state, the primary button, the conflict questions and the save dialog.
The installer is a fake: nothing is ever installed and the registry is never touched."""
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError
from fontplayground.ui import action_bar as action_bar_module
from fontplayground.ui import build as build_module
from fontplayground.ui import model as model_module
from fontplayground.ui import workers
from fontplayground.ui.action_bar import ActionBar, short_path
from fontplayground.ui.build import BuildController, BuildState
from fontplayground.ui.model import EMPTY_ERROR, GLYPH_NEAR_TEXT
from fontplayground.ui.theme import DARK, LIGHT
from tests.fixtures import cps, fake_face
from tests.test_build import (FULL, FakeInstaller, close_model, copying_forge, make_model, wait_state,
                              waiting_forge)

IDLE_TEXT = "Installs for your account only — no admin rights needed."
INSTALLED_TEXT = f"✓ Installed as “{FULL}” for your account."


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(model_module, "RESULT_DIR", tmp_path / "results")
    monkeypatch.setattr(build_module, "STAGE_DIR", tmp_path / "stage")


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    return a, b


@pytest.fixture
def model(qapp, faces):
    m = make_model(faces)
    yield m
    close_model(m)


@pytest.fixture
def installer(tmp_path):
    return FakeInstaller(tmp_path)


@pytest.fixture
def controller(model, installer, tmp_path):
    return BuildController(model, installer, windows_fonts_dir=tmp_path / "Windows" / "Fonts")


@pytest.fixture
def bar(qtbot, model, controller):
    b = ActionBar(model, controller)
    qtbot.addWidget(b)
    b.show()
    return b


@pytest.fixture
def forge_calls(monkeypatch, font_dir):
    calls: list = []
    monkeypatch.setattr(workers, "forge", copying_forge(font_dir, calls))
    return calls


@pytest.fixture
def forge_waits_for_cancel(monkeypatch):
    monkeypatch.setattr(workers, "forge", waiting_forge)


def shown(widget) -> bool:
    return not widget.isHidden()


def links(bar) -> list[str]:
    return [w.text() for w in (bar.show_file_link, bar.uninstall_link, bar.notes_link) if shown(w)]


def _install(qtbot, bar, controller) -> None:
    bar.primary_button.click()
    wait_state(qtbot, controller, BuildState.INSTALLED)


# ----- idle and invalid -------------------------------------------------------------------------------------
def test_idle_offers_install_and_a_copy(bar, model):
    assert bar.objectName() == "bar" and bar.height() == 84
    assert bar.family_edit.text() == "Test Mix" and bar.style_edit.text() == "Regular"
    assert bar.status_label.text() == IDLE_TEXT and bar.status_label.property("tone") == "muted"
    assert bar.detail_label.text() == "" and links(bar) == []
    assert bar.primary_button.text() == "Install" and bar.primary_button.isEnabled()
    assert shown(bar.save_button) and bar.save_button.text() == "Save a copy…" and bar.save_button.isEnabled()
    assert not shown(bar.progress_bar) and not shown(bar.cancel_button)


def test_an_invalid_recipe_shows_the_problem_and_disables_install(bar, model, faces):
    a, b = faces
    model.remove(a.key)
    model.remove(b.key)
    assert bar.status_label.text() == EMPTY_ERROR and bar.status_label.property("tone") == "danger"
    assert not bar.primary_button.isEnabled() and not bar.save_button.isEnabled()
    model.add(a)
    assert bar.status_label.text() == IDLE_TEXT and bar.primary_button.isEnabled()


def test_a_glyph_budget_warning_uses_the_warn_tone(bar, model, monkeypatch):
    monkeypatch.setattr(model, "glyph_warning", lambda: GLYPH_NEAR_TEXT)
    model.recompute_plan_now()                                 # planChanged: the bar looks again
    assert bar.status_label.text() == GLYPH_NEAR_TEXT and bar.status_label.property("tone") == "warn"
    assert bar.primary_button.isEnabled()


def test_names_are_two_way(qtbot, bar, model):
    bar.family_edit.selectAll()
    qtbot.keyClicks(bar.family_edit, "Mine")
    assert model.family == "Mine" and model.names_edited["family"]
    qtbot.keyClicks(bar.style_edit, " Two")
    assert model.style == "Regular Two"
    model.set_family("From Elsewhere", by_user=True)
    assert bar.family_edit.text() == "From Elsewhere"


# ----- building, cancel ------------------------------------------------------------------------------------
def test_building_shows_progress_and_locks_the_names(qtbot, bar, model, controller, forge_waits_for_cancel):
    bar.primary_button.click()
    assert controller.state is BuildState.BUILDING
    assert bar.primary_button.text() == "Installing…" and not bar.primary_button.isEnabled()
    assert bar.status_label.text().startswith("Building your font — ")
    assert shown(bar.progress_bar) and shown(bar.cancel_button) and bar.cancel_button.isEnabled()
    assert not shown(bar.save_button)
    assert not bar.family_edit.isEnabled() and not bar.style_edit.isEnabled()
    qtbot.waitUntil(lambda: bar.status_label.text() == "Building your font — waiting", timeout=5000)

    bar.cancel_button.click()
    assert not bar.cancel_button.isEnabled()                   # stopping
    wait_state(qtbot, controller, BuildState.CANCELLED)
    qtbot.waitUntil(lambda: bar.family_edit.isEnabled(), timeout=5000)
    assert bar.status_label.text() == "Cancelled." and bar.status_label.property("tone") == "muted"
    assert bar.primary_button.text() == "Install" and bar.primary_button.isEnabled()
    assert not shown(bar.progress_bar) and not shown(bar.cancel_button) and shown(bar.save_button)


def test_saving_shows_saving(qtbot, bar, controller, forge_waits_for_cancel, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "x.ttf"), ""))
    bar.save_button.click()
    assert controller.intent == "save" and bar.primary_button.text() == "Saving…"
    controller.cancel()
    wait_state(qtbot, controller, BuildState.CANCELLED)


# ----- installed, update, uninstall -------------------------------------------------------------------------
def test_installed_then_a_change_offers_an_update(qtbot, bar, model, controller, installer, forge_calls):
    _install(qtbot, bar, controller)
    assert installer.installs == [("Test Mix-Regular.ttf", FULL, True)]
    assert bar.status_label.text() == INSTALLED_TEXT and bar.status_label.property("tone") == "ok"
    assert bar.detail_label.text() == "Choose it in any app's font list."
    assert links(bar) == ["Show file", "Uninstall", "Notes (1)"]
    assert bar.primary_button.text() == "Installed ✓" and not bar.primary_button.isEnabled()
    assert bar.primary_button.property("done") is True
    assert not shown(bar.progress_bar) and not shown(bar.cancel_button)

    model.set_style("Bold")
    assert bar.style_edit.text() == "Bold"
    assert bar.primary_button.text() == "Update installed font" and bar.primary_button.isEnabled()
    assert bar.primary_button.property("done") is False
    _install(qtbot, bar, controller)
    assert installer.installs[-1] == ("Test Mix-Bold.ttf", "Test Mix Bold", True)
    assert bar.primary_button.text() == "Installed ✓"


def test_uninstall_link_removes_the_font(qtbot, bar, controller, installer, forge_calls):
    _install(qtbot, bar, controller)
    bar.uninstall_link.click()
    assert installer.uninstalls == [FULL]
    assert bar.status_label.text() == "Removed from your fonts." and bar.status_label.property("tone") == "muted"
    assert links(bar) == [] and bar.primary_button.text() == "Install" and bar.primary_button.isEnabled()


def test_show_file_opens_the_folder(qtbot, bar, controller, forge_calls, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(action_bar_module, "open_folder", lambda folder: opened.append(folder) or True)
    _install(qtbot, bar, controller)
    bar.show_file_link.click()
    assert opened == [str(tmp_path / "user")]


def test_notes_and_details_ask_for_the_report(qtbot, bar, controller, forge_calls, monkeypatch):
    _install(qtbot, bar, controller)
    with qtbot.waitSignal(bar.detailsRequested, timeout=1000):
        bar.notes_link.click()

    def broken(spec, output_path, progress=None):
        raise ForgeError("merge", None, "the fonts disagree")
    monkeypatch.setattr(workers, "forge", broken)
    bar.model.set_style("Bold")
    bar.primary_button.click()
    wait_state(qtbot, controller, BuildState.FAILED)
    assert bar.status_label.text() == "Couldn't build the font: [merge] the fonts disagree"
    assert bar.status_label.property("tone") == "danger"
    assert links(bar) == ["Details"]
    with qtbot.waitSignal(bar.detailsRequested, timeout=1000):
        bar.notes_link.click()


def test_no_notes_link_without_warnings(qtbot, bar, controller, monkeypatch, font_dir):
    monkeypatch.setattr(workers, "forge", copying_forge(font_dir, [], warnings=()))
    _install(qtbot, bar, controller)
    assert links(bar) == ["Show file", "Uninstall"]


# ----- conflicts ---------------------------------------------------------------------------------------------
def _catalog_face(model, faces, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"font")
    other = fake_face(cps("ab"), path=str(path), family="Test Mix")
    a, b = faces
    model.set_catalog({a.key: a, b.key: b, other.key: other})
    return path


def test_a_name_windows_already_has_is_refused(bar, model, faces, controller, installer, forge_calls, monkeypatch,
                                               tmp_path):
    _catalog_face(model, faces, tmp_path / "Windows" / "Fonts" / "testmix.ttf")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kw: warned.append(args[1:3]))
    bar.primary_button.click()
    assert warned == [("Choose another name",
                       "Windows already has a font called “Test Mix” — choose another name.")]
    assert controller.state is BuildState.IDLE and forge_calls == [] and installer.installs == []


def test_replacing_a_forged_font_asks_first(qtbot, bar, model, faces, controller, installer, forge_calls,
                                            monkeypatch, tmp_path):
    path = _catalog_face(model, faces, tmp_path / "user" / "Test Mix-Regular.ttf")
    installer.forged.add(str(path))
    asked = []
    answer = [QMessageBox.StandardButton.No]
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kw: asked.append(args[1:3]) or answer[0])
    bar.primary_button.click()
    assert asked == [("Replace the font?", f"Replace the “{FULL}” you installed earlier?")]
    assert controller.state is BuildState.IDLE and forge_calls == []
    answer[0] = QMessageBox.StandardButton.Yes
    _install(qtbot, bar, controller)
    assert len(asked) == 2 and installer.installs == [("Test Mix-Regular.ttf", FULL, True)]


# ----- save --------------------------------------------------------------------------------------------------
def test_save_a_copy_asks_for_a_path(qtbot, bar, model, controller, installer, forge_calls, monkeypatch, tmp_path):
    out = tmp_path / "copies" / "Mine.ttf"
    asked = []
    answer = [("", "")]
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kw: asked.append(args) or answer[0])
    bar.save_button.click()                                    # cancelled dialog: nothing happens
    assert asked == [(bar, "Save the font as", model.output, "TrueType font (*.ttf)")]
    assert controller.state is BuildState.IDLE and forge_calls == []

    answer[0] = (str(out), "TrueType font (*.ttf)")
    bar.save_button.click()
    wait_state(qtbot, controller, BuildState.SAVED)
    assert out.is_file() and installer.installs == []
    assert bar.status_label.text() == f"✓ Saved to {short_path(str(out))}"
    assert bar.status_label.property("tone") == "ok"
    assert links(bar) == ["Show file", "Notes (1)"]
    assert bar.primary_button.text() == "Install" and bar.primary_button.isEnabled()


def test_short_path_uses_a_tilde_for_the_home_folder():
    home = Path.home()
    assert short_path(str(home / "Documents" / "X.ttf")) == f"~{os.sep}Documents{os.sep}X.ttf"
    assert short_path("Z:/elsewhere/X.ttf") == str(Path("Z:/elsewhere/X.ttf"))


def test_without_install_support_the_primary_saves(qtbot, model, faces, forge_calls, monkeypatch, tmp_path):
    installer = FakeInstaller(tmp_path, supported=False)
    controller = BuildController(model, installer, windows_fonts_dir=tmp_path / "Windows" / "Fonts")
    bar = ActionBar(model, controller)
    qtbot.addWidget(bar)
    bar.show()
    assert bar.primary_button.text() == "Save…" and bar.primary_button.isEnabled()
    assert not shown(bar.save_button)
    assert bar.status_label.text() == "Saves a .ttf file you can install yourself."
    out = tmp_path / "Mine.ttf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kw: (str(out), ""))
    bar.primary_button.click()
    assert bar.primary_button.text() == "Saving…" and not bar.primary_button.isEnabled()
    wait_state(qtbot, controller, BuildState.SAVED)
    assert out.is_file() and installer.installs == []
    assert bar.status_label.text() == f"✓ Saved to {short_path(str(out))}"
    assert bar.primary_button.text() == "Save…" and not shown(bar.save_button)


# ----- theme -------------------------------------------------------------------------------------------------
def test_apply_theme_restyles_the_bar(bar):
    assert LIGHT.surface in bar.styleSheet()
    bar.apply_theme(DARK)
    assert DARK.surface in bar.styleSheet() and LIGHT.accent not in bar.styleSheet()
    assert "$" not in bar.styleSheet()
