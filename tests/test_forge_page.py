import os
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError, ForgeReport, MaterialReport
from fontplayground.ui import forge_page
from fontplayground.ui import workers
from fontplayground.ui.forge_page import (HINT_ARRIVE, HINT_CANCELLED, HINT_STALE, STATE_FORGING, STATE_READY,
                                          STATE_RESULT, ForgePage, compact_path, short_path, summary_sentence)
from fontplayground.ui.model import ForgeModel
from fontplayground.ui.preview import PreviewWidget
from tests.fixtures import cps, fake_face

FAMILY = "Fixture A Fixture B"


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    return a, b


def _cleanup_result(model: ForgeModel) -> None:
    # Best effort: Qt's offscreen font database on Windows may keep a loaded result mapped, so unlink can fail.
    if model.is_busy():
        model.cancel(wait_ms=15000)
    path = model.result_path
    model.discard_result()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def model(qapp, faces):
    a, b = faces
    m = ForgeModel()
    m.set_catalog({a.key: a, b.key: b})
    m.add(a)
    m.add(b)
    yield m
    _cleanup_result(m)


@pytest.fixture
def page(qtbot, model):
    p = ForgePage(model, PreviewWidget(sizes=(12,)))
    qtbot.addWidget(p)
    p.show()
    return p


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
def fake_forge(monkeypatch, font_dir):
    """A quick forge(): copies fixture A to the output and reports two materials and one warning."""
    def forge(spec, output_path, progress=None):
        progress("plan", 0.0)
        time.sleep(0.05)
        shutil.copyfile(font_dir / "A.ttf", output_path)
        progress("done", 1.0)
        return ForgeReport([MaterialReport("Fixture A Regular", 5, ["latin"]),
                            MaterialReport("Fixture B Bold", 2, ["han", "cjk_symbols"], ["made bolder synthetically"])],
                           7, 8, ["Fixture B Bold: made bolder synthetically"], str(output_path))
    monkeypatch.setattr(workers, "forge", forge)


def _forge(qtbot, page, model):
    with qtbot.waitSignal(model.resultReady, timeout=60000):
        page.activate()
    assert page.state() == STATE_RESULT


# ----- helpers ---------------------------------------------------------------------------------------
def test_path_helpers_and_summary_sentence():
    home = Path.home()
    assert short_path(str(home / "Documents" / "X.ttf")) == f"~{os.sep}Documents{os.sep}X.ttf"
    assert short_path("D:/elsewhere/X.ttf") == str(Path("D:/elsewhere/X.ttf"))
    assert compact_path(str(home / "Documents" / "X.ttf")) == f"~{os.sep}Documents{os.sep}X.ttf"
    long = str(home / "Documents" / "Fonts" / "A very long project folder name" / "Family-Style.ttf")
    assert compact_path(long) == f"~{os.sep}…{os.sep}Family-Style.ttf"
    assert compact_path("D:/x/y/z/Family.ttf", max_len=10) == f"D:{os.sep}…{os.sep}Family.ttf"
    materials = [MaterialReport("Segoe UI Regular", 10, ["latin", "greek", "cyrillic", "symbols", "other"]),
                 MaterialReport("Microsoft YaHei Regular", 20, ["han", "kana"]),
                 MaterialReport("Spare Bold", 0, [])]
    assert summary_sentence(materials) == ("Segoe UI Regular supplied Latin, Greek, Cyrillic, Punctuation & symbols …"
                                           " · Microsoft YaHei Regular supplied Han, Kana · Spare Bold supplied nothing")
    assert "Everything else" in summary_sentence(materials, limit=None)


# ----- form ------------------------------------------------------------------------------------------
def test_form_is_prefilled_from_the_model_and_edits_go_back(qtbot, page, model):
    assert page.family_edit.text() == FAMILY and page.style_edit.text() == "Regular"
    assert page.path_label.text() == f"~{os.sep}Documents{os.sep}{FAMILY}-Regular.ttf"
    assert page.path_label.toolTip() == model.output
    assert page.column.maximumWidth() == 760

    page.family_edit.clear()
    qtbot.keyClicks(page.family_edit, "Mine")
    assert model.family == "Mine" and model.names_edited["family"] is True
    assert page.path_label.text() == f"~{os.sep}Documents{os.sep}Mine-Regular.ttf"   # the output follows
    page.style_edit.setText("Italic")
    assert model.style == "Italic" and model.names_edited["style"] is True
    assert page.path_label.text() == f"~{os.sep}Documents{os.sep}Mine-Italic.ttf"

    model.set_style("Heavy", by_user=False)   # model -> edit without echoing back as a user edit
    assert page.style_edit.text() == "Heavy" and model.names_edited["style"] is True
    edits = model.names_edited
    page.style_edit.setText("Heavy")          # same text again: nothing changes
    assert model.names_edited == edits and model.style == "Heavy"


def test_change_button_asks_for_a_file(qtbot, page, model, monkeypatch, tmp_path):
    asked = []
    chosen = str(tmp_path / "chosen.ttf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args, **kw: asked.append(args[1:]) or (chosen, "TrueType font (*.ttf)"))
    page.change_button.click()
    assert asked == [("Save the font as", str(Path.home() / "Documents" / f"{FAMILY}-Regular.ttf"),
                      "TrueType font (*.ttf)")]
    assert model.output == chosen and model.names_edited["output"] is True
    assert page.path_label.text() == short_path(chosen)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kw: ("", ""))
    page.change_button.click()                # cancelled: nothing changes
    assert model.output == chosen


# ----- ready state -----------------------------------------------------------------------------------
def test_ready_state_shows_the_composite_preview_and_the_recap(qtbot, page, model, faces):
    a, b = faces
    assert page.state() == STATE_READY and page.hint_label.text() == HINT_ARRIVE
    assert page.preview.in_plan_mode() and page.preview.parentWidget() is page.ready_card
    assert page.preview.isVisible() and page.hint_label.isVisible()
    assert page.primary_state() == ("Rebuild", True)
    model.recompute_plan_now()
    model.set_sample_text("ab漢 한")
    assert page.preview.sample_text() == "ab漢 한"
    assert page.recap_label.text() == "2 fonts · 7 characters · 1 sample character missing: 한"
    assert page.recap_label.toolTip() == "한"
    assert page.preview.missing_characters() == ["한"]
    page.preview.editor.setPlainText("ab漢")    # typing in the preview reaches the model
    assert model.sample_text == "ab漢"
    assert page.recap_label.text() == "2 fonts · 7 characters · sample fully covered"
    model.remove(b.key)
    model.recompute_plan_now()
    assert page.recap_label.text() == "1 font · 5 characters · 1 sample character missing: 漢"
    model.remove(a.key)
    model.recompute_plan_now()
    assert page.recap_label.text() == "0 fonts · 0 characters"
    assert page.primary_state() == ("Rebuild", False)
    assert page.hint_label.text() == "Can't forge yet — Add at least one font."
    assert "#b3261e" in page.hint_label.styleSheet()


def test_activate_does_not_forge_an_invalid_spec(qtbot, page, model):
    model.set_family("")
    page.activate()
    assert not model.is_busy() and page.state() == STATE_READY
    assert page.hint_label.text() == "Can't forge yet — Family name is empty."
    assert page.primary_state() == ("Rebuild", False)
    page.primary_clicked()                    # disabled: still nothing
    assert not model.is_busy()
    model.set_family("Back")
    assert page.hint_label.text() == HINT_ARRIVE and page.primary_state() == ("Rebuild", True)


# ----- forging and the result ------------------------------------------------------------------------
def test_activate_forges_for_real_and_shows_the_result(qtbot, page, model):
    stages = []
    model.progress.connect(lambda text, fraction: stages.append(text))
    with qtbot.waitSignal(model.resultReady, timeout=60000):
        page.activate()
        assert model.is_busy() and page.state() == STATE_FORGING
        assert page.preview.parentWidget() is page.forging_card and page.preview.in_plan_mode()
        assert page.primary_state() == ("Forging…", False)
        assert page.stage_label.text() == "Starting…" and page.cancel_button.isEnabled()
    report = model.result_report
    assert page.state() == STATE_RESULT and page.preview.parentWidget() is page.result_card
    assert page.preview.isVisible() and page.summary_label.isVisible() and not page.stage_label.isVisible()
    assert page.stage_label.text() == "Done." and page.progress_bar.value() == 100
    assert "Preparing Fixture B Bold…" in stages
    assert page.title_label.text() == f"Forged ✓ — {FAMILY} Regular"
    assert page.summary_label.text() == ("Fixture A Regular supplied Latin"
                                         " · Fixture B Bold supplied Han, CJK symbols & fullwidth")
    assert not page.preview.in_plan_mode() and page.preview.current_family() == FAMILY
    assert page.details_text.toPlainText() == report.as_text() and page.details_text.isHidden()
    assert [w.text() for w in page.warning_labels()] == report.warnings
    assert page.recap_label.text().startswith("2 fonts · 7 characters · ")
    assert page.missing_label.text().startswith("Not in this font: ") and not page.missing_label.isHidden()
    assert "漢" not in page.missing_label.text() and "한" in page.missing_label.toolTip()
    text, enabled = page.primary_state()
    assert text.startswith("Save to") and enabled
    assert not page.open_folder_button.isEnabled()
    page.activate()                           # a fresh result: nothing to do
    assert not model.is_busy() and page.state() == STATE_RESULT


def test_primary_saves_then_a_change_makes_it_stale(qtbot, page, model, faces, fake_forge, tmp_path, monkeypatch):
    a, b = faces
    _forge(qtbot, page, model)
    out = tmp_path / "out.ttf"
    model.set_output(str(out))
    assert page.primary_state() == (f"Save to {compact_path(str(out))}", True)
    page.primary_clicked()
    assert out.is_file() and out.read_bytes() == Path(model.result_path).read_bytes()
    assert page.primary_state() == ("Saved ✓", True) and page.open_folder_button.isEnabled()

    opened = []
    monkeypatch.setattr(forge_page, "open_folder", lambda folder: opened.append(folder) or True)
    page.primary_clicked()                    # Saved ✓: open the folder
    assert opened == [str(tmp_path)]
    page.open_folder_button.click()
    assert opened == [str(tmp_path)] * 2

    model.set_output(str(tmp_path / "elsewhere.ttf"))   # a new place to save to: not saved there yet
    assert page.primary_state()[0].startswith("Save to") and page.state() == STATE_RESULT
    model.set_output(str(out))
    assert page.primary_state() == ("Saved ✓", True)

    with qtbot.waitSignal(model.resultStale):
        model.set_adjust(b.key, 600, None)
    assert page.primary_state() == ("Rebuild", True) and page.state() == STATE_READY
    assert page.hint_label.text() == HINT_STALE and "Rebuild" in page.hint_label.text()
    assert page.preview.in_plan_mode() and page.preview.parentWidget() is page.ready_card
    assert page.recap_label.text().startswith("2 fonts · ")
    qtbot.wait(20)                            # the reparented preview shows once the event loop runs
    assert page.preview.isVisible() and page.hint_label.isVisible() and not page.summary_label.isVisible()

    _forge(qtbot, page, model)                # Rebuild via the primary button
    assert page.primary_state() == (f"Save to {compact_path(str(out))}", True)   # a new result is not saved


def test_save_asks_before_replacing_a_file_it_did_not_write(qtbot, page, model, fake_forge, tmp_path, monkeypatch):
    _forge(qtbot, page, model)
    out = tmp_path / "out.ttf"
    out.write_bytes(b"old")
    model.set_output(str(out))
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args, **kw: asked.append(args[2]) or QMessageBox.StandardButton.No)
    page.primary_clicked()
    assert len(asked) == 1 and short_path(str(out)) in asked[0]
    assert out.read_bytes() == b"old" and page.primary_state()[0].startswith("Save to")
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *args, **kw: asked.append(args[2]) or QMessageBox.StandardButton.Yes)
    page.primary_clicked()
    assert len(asked) == 2 and out.read_bytes() == Path(model.result_path).read_bytes()
    assert page.primary_state() == ("Saved ✓", True)
    monkeypatch.setattr(forge_page, "open_folder", lambda folder: True)
    page.primary_clicked()                    # Saved ✓ opens the folder; no question this time
    assert len(asked) == 2


def test_cancel_returns_to_the_ready_state(qtbot, page, model, forge_waits_for_cancel):
    page.activate()
    assert model.is_busy() and page.state() == STATE_FORGING
    assert page.primary_state() == ("Forging…", False)
    page.primary_clicked()                    # a no-op while busy
    qtbot.wait(20)
    assert page.preview.isVisible() and page.progress_bar.isVisible() and page.cancel_button.isVisible()
    with qtbot.waitSignal(model.resultCancelled, timeout=15000):
        page.cancel_button.click()
        assert not page.cancel_button.isEnabled() and page.stage_label.text() == "Stopping…"
    qtbot.waitUntil(lambda: not model.is_busy() and page.state() == STATE_READY, timeout=15000)
    assert page.hint_label.text() == HINT_CANCELLED and "Rebuild" in page.hint_label.text()
    assert page.primary_state() == ("Rebuild", True) and page.preview.in_plan_mode()
    assert model.result_path is None


def test_failure_returns_to_the_ready_state_with_the_error(qtbot, tmp_path):
    ghost = fake_face(cps("ab"), path=str(tmp_path / "missing.ttf"), family="Ghost")
    model = ForgeModel()
    model.add(ghost)
    page = ForgePage(model, PreviewWidget(sizes=(12,)))
    qtbot.addWidget(page)
    page.show()
    with qtbot.waitSignal(model.resultFailed, timeout=60000):
        page.activate()
        assert page.state() == STATE_FORGING
    assert page.state() == STATE_READY and not model.is_busy()
    assert page.hint_label.text().startswith("Forging failed: [prepare (Ghost Regular)] ")
    assert page.hint_label.text().endswith(" Press Rebuild to try again.")
    assert "Traceback" in page.hint_label.toolTip() and "#b3261e" in page.hint_label.styleSheet()
    assert page.primary_state() == ("Rebuild", True)


# ----- result card buttons ---------------------------------------------------------------------------
def test_install_button_saves_installs_and_offers_removal(qtbot, page, model, fake_forge, tmp_path, monkeypatch):
    installs, removals = [], []
    monkeypatch.setattr(forge_page.install, "is_supported", lambda: True)
    monkeypatch.setattr(forge_page.install, "install_font_for_user",
                        lambda path, full_name=None: installs.append((Path(path), full_name)) or tmp_path / "installed.ttf")
    monkeypatch.setattr(forge_page.install, "uninstall_font_for_user", lambda name: removals.append(name) or True)
    _forge(qtbot, page, model)
    assert not page.install_button.isHidden() and page.saved_label.isHidden() and page.remove_button.isHidden()
    out = tmp_path / "out.ttf"
    model.set_output(str(out))
    page.install_button.click()
    assert out.is_file() and installs == [(out, f"{FAMILY} Regular")]
    assert page.saved_label.text() == f"Installed for your account as {FAMILY} Regular"
    assert not page.saved_label.isHidden() and "#2f8f46" in page.saved_label.styleSheet()
    assert not page.remove_button.isHidden()
    assert page.primary_state() == ("Saved ✓", True) and page.open_folder_button.isEnabled()

    page.remove_button.click()
    assert removals == [f"{FAMILY} Regular"]
    assert page.saved_label.text() == "Removed from your fonts." and page.remove_button.isHidden()
    page.remove_button.click()                # nothing installed any more: nothing happens
    assert removals == [f"{FAMILY} Regular"]


def test_install_errors_are_reported(qtbot, page, model, fake_forge, tmp_path, monkeypatch):
    def refuse(path, full_name=None):
        raise OSError("the font folder is locked")
    monkeypatch.setattr(forge_page.install, "is_supported", lambda: True)
    monkeypatch.setattr(forge_page.install, "install_font_for_user", refuse)
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kw: shown.append(args[1:3]) or QMessageBox.StandardButton.Ok)
    _forge(qtbot, page, model)
    model.set_output(str(tmp_path / "out.ttf"))
    page.install_button.click()
    assert shown == [("Could not install the font", "the font folder is locked")]
    assert page.saved_label.isHidden() and page.remove_button.isHidden()
    assert (tmp_path / "out.ttf").is_file() and page.primary_state() == ("Saved ✓", True)   # the save itself worked


def test_install_button_is_hidden_when_not_supported(qtbot, model, monkeypatch):
    monkeypatch.setattr(forge_page.install, "is_supported", lambda: False)
    page = ForgePage(model, PreviewWidget(sizes=(12,)))
    qtbot.addWidget(page)
    page.show()
    assert page.install_button.isHidden()
    assert not page.open_folder_button.isHidden() and not page.start_over_button.isHidden()


def test_start_over_details_and_warnings(qtbot, page, model, fake_forge):
    _forge(qtbot, page, model)
    with qtbot.waitSignal(page.startOverClicked):
        page.start_over_button.click()
    assert [w.text() for w in page.warning_labels()] == ["Fixture B Bold: made bolder synthetically"]
    assert page.warning_labels()[0].objectName() == "warning"
    assert page.details_text.isHidden()
    page.details_button.click()
    assert not page.details_text.isHidden() and page.details_text.toPlainText() == model.result_report.as_text()
    page.details_button.click()
    assert page.details_text.isHidden()
    assert page.preview.current_family() == "Fixture A"   # the fake result is a copy of fixture A
    model.set_sample_text("abc 漢")
    assert page.missing_label.text() == "Not in this font: 漢"   # the real result, not the plan


def test_primary_state_changed_fires_only_when_the_tuple_changes(qtbot, page, model, faces, fake_forge, tmp_path):
    a, b = faces
    seen = []
    page.primaryStateChanged.connect(lambda: seen.append(page.primary_state()))
    _forge(qtbot, page, model)
    assert seen == [("Forging…", False), (f"Save to {compact_path(model.output)}", True)]
    out = tmp_path / "out.ttf"
    model.set_output(str(out))
    assert seen[-1] == (f"Save to {compact_path(str(out))}", True) and len(seen) == 3
    page.primary_clicked()
    assert seen[-1] == ("Saved ✓", True) and len(seen) == 4
    model.set_sample_text("zzz")              # not part of the result: no change
    model.set_output(str(out))                # the same path: no change
    assert len(seen) == 4
    model.set_adjust(b.key, 700, None)
    assert seen[-1] == ("Rebuild", True) and len(seen) == 5
    model.set_output(str(tmp_path / "other.ttf"))   # still Rebuild: no change
    assert len(seen) == 5
    model.set_family("")
    assert seen[-1] == ("Rebuild", False) and len(seen) == 6
