"""BuildController: build when needed, then install or save a copy; stale -> update; failure, cancel, uninstall,
name conflicts and reset. The installer is a fake: nothing is ever installed and the registry is never touched."""
from dataclasses import replace
from pathlib import Path

import pytest

from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError
from fontplayground.ui import build as build_module
from fontplayground.ui import model as model_module
from fontplayground.ui import workers
from fontplayground.ui.build import BuildController, BuildState
from fontplayground.ui.install import InstallNotSupported
from fontplayground.ui.model import ForgeModel
from tests.fakes import NOTE, FakeInstaller, copying_forge, waiting_forge
from tests.fixtures import cps, fake_face

FAMILY = "Test Mix"
FULL = "Test Mix Regular"
STAGED = "Test Mix-Regular.ttf"


def make_model(faces) -> ForgeModel:
    a, b = faces
    m = ForgeModel()
    m.set_catalog({a.key: a, b.key: b})
    m.add(a)
    m.add(b)
    m.set_family(FAMILY)
    return m


def close_model(m: ForgeModel) -> None:
    if m.is_busy():
        m.cancel(wait_ms=15000)
    if m.worker is not None:
        m.worker.wait(15000)
    m.discard_result()


def wait_state(qtbot, controller, state, timeout=10000) -> None:
    qtbot.waitUntil(lambda: controller.state is state, timeout=timeout)


# ----- fixtures ----------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    """Results and staged copies live under tmp_path, never in the real temp folder."""
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
def windows_fonts(tmp_path):
    return tmp_path / "Windows" / "Fonts"


@pytest.fixture
def controller(model, installer, windows_fonts):
    return BuildController(model, installer, windows_fonts_dir=windows_fonts)


@pytest.fixture
def forge_calls(monkeypatch, font_dir):
    calls: list = []
    monkeypatch.setattr(workers, "forge", copying_forge(font_dir, calls))
    return calls


@pytest.fixture
def forge_waits_for_cancel(monkeypatch):
    monkeypatch.setattr(workers, "forge", waiting_forge)


def _install(qtbot, controller) -> None:
    controller.install()
    wait_state(qtbot, controller, BuildState.INSTALLED)


# ----- install -------------------------------------------------------------------------------------------
def test_install_without_a_result_builds_then_installs_under_the_font_name(qtbot, controller, model, installer,
                                                                           forge_calls, tmp_path):
    seen = []
    controller.changed.connect(lambda: seen.append((controller.state, controller.stage)))
    assert controller.state is BuildState.IDLE and controller.intent is None and controller.report is None
    controller.install()
    assert controller.state is BuildState.BUILDING and controller.intent == "install"
    wait_state(qtbot, controller, BuildState.INSTALLED)

    assert len(forge_calls) == 1
    assert installer.installs == [(STAGED, FULL, True)]          # the staged copy existed while it was installed
    assert not (tmp_path / "stage" / STAGED).exists()             # and is gone afterwards
    assert controller.installed_name == FULL
    assert controller.installed_path == tmp_path / "user" / STAGED
    assert controller.shown_file() == controller.installed_path
    assert controller.report is model.result_report and controller.report.warnings == [NOTE]
    assert controller.intent is None and controller.error is None and not controller.is_update()

    states = [s for s, _ in seen]
    assert states[0] is BuildState.BUILDING and states[-1] is BuildState.INSTALLED
    assert set(states) == {BuildState.BUILDING, BuildState.INSTALLED}
    stages = [t for s, t in seen if s is BuildState.BUILDING]
    assert "Starting…" in stages and "Combining the fonts…" in stages
    assert controller.fraction == 1.0


def test_install_with_a_fresh_result_installs_at_once(qtbot, controller, model, installer, forge_calls):
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()                                        # a build the controller did not start
    assert controller.state is BuildState.BUILT and controller.intent is None
    assert controller.report is model.result_report
    forge_calls.clear()
    controller.install()
    assert controller.state is BuildState.INSTALLED and forge_calls == []
    assert installer.installs == [(STAGED, FULL, True)]


def test_install_is_ignored_while_busy_or_invalid(qtbot, controller, model, installer, forge_waits_for_cancel):
    model.set_family("")                                       # the spec is not valid without a family name
    assert model.validity() != ""
    controller.install()
    controller.save_copy("anything.ttf")
    assert controller.state is BuildState.IDLE and not model.is_busy()
    model.set_family(FAMILY)
    controller.install()
    assert controller.state is BuildState.BUILDING
    controller.save_copy("anything.ttf")                       # busy: ignored
    assert controller.intent == "install"
    controller.cancel()
    wait_state(qtbot, controller, BuildState.CANCELLED)


def test_a_later_change_offers_an_update_and_installing_again_asks_nothing(qtbot, controller, model, installer,
                                                                           faces, forge_calls):
    a, b = faces
    _install(qtbot, controller)
    assert controller.conflict() == ("none", "")
    changes = []
    controller.changed.connect(lambda: changes.append(1))
    model.set_adjust(b.key, 600, None)                          # the result is stale now
    assert changes and controller.is_update()
    assert controller.state is BuildState.INSTALLED            # still installed, just not the latest
    assert controller.conflict() == ("none", "")               # this controller installed that name itself
    controller.install()
    assert controller.state is BuildState.BUILDING
    wait_state(qtbot, controller, BuildState.INSTALLED)
    assert installer.installs == [(STAGED, FULL, True)] * 2 and len(forge_calls) == 2
    assert not controller.is_update() and installer.uninstalls == []


def test_a_new_result_the_controller_did_not_install_is_an_update(qtbot, controller, model, forge_calls):
    _install(qtbot, controller)
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()
    assert controller.state is BuildState.BUILT and controller.is_update()


def test_updating_under_a_new_name_removes_the_font_installed_before(qtbot, controller, model, installer, forge_calls):
    _install(qtbot, controller)
    model.set_style("Bold")
    assert controller.is_update()
    _install(qtbot, controller)
    assert installer.installs[-1] == ("Test Mix-Bold.ttf", "Test Mix Bold", True)
    assert installer.uninstalls == [FULL] and controller.installed_name == "Test Mix Bold"


def test_install_errors_fail_with_a_plain_message(qtbot, controller, model, installer, forge_calls, tmp_path):
    installer.install_error = OSError("the font folder is locked")
    controller.install()
    wait_state(qtbot, controller, BuildState.FAILED)
    assert controller.error == "Couldn't install the font: the font folder is locked"
    assert controller.installed_name is None and controller.installed_path is None
    assert not (tmp_path / "stage" / STAGED).exists()
    installer.install_error = None
    controller.install()                                       # the result is still fresh: no second build
    assert controller.state is BuildState.INSTALLED and len(forge_calls) == 1


# ----- save a copy ---------------------------------------------------------------------------------------
def test_save_copy_builds_writes_the_file_and_remembers_it(qtbot, controller, model, installer, forge_calls, tmp_path):
    out = tmp_path / "saved" / "Mine.ttf"
    controller.save_copy(out)
    assert controller.state is BuildState.BUILDING and controller.intent == "save"
    wait_state(qtbot, controller, BuildState.SAVED)
    assert out.is_file() and out.read_bytes() == Path(model.result_path).read_bytes()
    assert controller.saved_path == out and controller.shown_file() == out
    assert model.output == str(out) and model.names_edited["output"]
    assert installer.installs == [] and controller.installed_name is None

    again = tmp_path / "again.ttf"
    controller.save_copy(str(again))                           # a fresh result: saved at once
    assert controller.state is BuildState.SAVED and again.is_file() and len(forge_calls) == 1
    assert controller.saved_path == again


def test_save_errors_fail_with_a_plain_message(qtbot, controller, model, forge_calls, monkeypatch, tmp_path):
    def refuse(path):
        raise OSError("the disk is full")
    monkeypatch.setattr(model, "save_to", refuse)
    controller.save_copy(tmp_path / "x.ttf")
    wait_state(qtbot, controller, BuildState.FAILED)
    assert controller.error == "Couldn't save the font: the disk is full"
    assert controller.saved_path is None


# ----- failure, cancel ------------------------------------------------------------------------------------
def test_a_failed_build_says_why(qtbot, controller, model, installer, monkeypatch):
    def broken(spec, output_path, progress=None):
        raise ForgeError("merge", None, "the fonts disagree")
    monkeypatch.setattr(workers, "forge", broken)
    controller.install()
    wait_state(qtbot, controller, BuildState.FAILED)
    assert controller.error == "Couldn't build the font: [merge] the fonts disagree"
    assert controller.error_detail.startswith("[merge] the fonts disagree")
    assert "Traceback (most recent call last):" in controller.error_detail
    assert installer.installs == [] and controller.intent is None


def test_cancel_stops_the_build(qtbot, controller, model, installer, forge_waits_for_cancel):
    controller.install()
    assert controller.state is BuildState.BUILDING
    controller.cancel()
    assert controller.stage == "Stopping…" and controller.stopping
    wait_state(qtbot, controller, BuildState.CANCELLED)
    qtbot.waitUntil(lambda: not model.is_busy(), timeout=5000)
    assert installer.installs == [] and controller.intent is None and not controller.stopping


# ----- uninstall ------------------------------------------------------------------------------------------
def test_uninstall_removes_the_font_and_leaves_a_notice(qtbot, controller, installer, forge_calls):
    _install(qtbot, controller)
    controller.uninstall()
    assert installer.uninstalls == [FULL]
    assert controller.state is BuildState.IDLE and controller.notice == "Removed from your fonts."
    assert controller.installed_name is None and controller.installed_path is None
    assert controller.shown_file() is None and not controller.is_update()

    controller.install()                                       # fresh result: installed again at once
    assert controller.state is BuildState.INSTALLED and controller.notice is None
    installer.uninstall_result = False
    controller.uninstall()
    assert controller.notice == "That font was no longer installed." and controller.state is BuildState.IDLE
    controller.uninstall()                                     # nothing installed: nothing happens
    assert installer.uninstalls == [FULL, FULL]


# ----- conflicts ------------------------------------------------------------------------------------------
def _with_catalog_face(model, faces, path: Path, family=FAMILY, style="Regular"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"font")
    other = fake_face(cps("ab"), path=str(path), family=family, style=style)
    a, b = faces
    model.set_catalog({a.key: a, b.key: b, other.key: other})
    return path


def test_no_conflict_for_a_new_name(controller, model, faces, tmp_path):
    _with_catalog_face(model, faces, tmp_path / "user" / "other.ttf", family="Something Else")
    assert controller.conflict() == ("none", "")


def test_a_windows_font_with_the_same_family_blocks(controller, model, faces, windows_fonts):
    _with_catalog_face(model, faces, windows_fonts / "testmix.ttf", family="test MIX", style="Bold")
    assert controller.conflict() == ("block", "Windows already has a font called “Test Mix” — choose another name.")


def test_a_font_the_user_installed_elsewhere_blocks(controller, model, faces, tmp_path):
    _with_catalog_face(model, faces, tmp_path / "user" / "mine.ttf")
    assert controller.conflict() == ("block",
                                     "You already have a font called “Test Mix” installed — choose another name.")


def test_a_forged_font_installed_earlier_asks_to_replace(qtbot, controller, model, faces, installer, forge_calls,
                                                          tmp_path):
    path = _with_catalog_face(model, faces, tmp_path / "user" / STAGED)
    installer.forged.add(str(path))
    assert controller.conflict() == ("replace", "Replace the “Test Mix Regular” you installed earlier?")
    _install(qtbot, controller)                                # installed by this controller: no question
    assert controller.conflict() == ("none", "")


def test_a_forged_font_of_another_style_is_no_conflict(controller, model, faces, installer, tmp_path):
    path = _with_catalog_face(model, faces, tmp_path / "user" / "Test Mix-Bold.ttf", style="Bold")
    installer.forged.add(str(path))
    assert controller.conflict() == ("none", "")


def test_a_catalog_face_whose_file_is_gone_is_no_conflict(controller, model, faces, tmp_path):
    path = _with_catalog_face(model, faces, tmp_path / "user" / "gone.ttf")
    path.unlink()
    assert controller.conflict() == ("none", "")


def test_a_native_family_name_counts_too(controller, model, faces, windows_fonts):
    path = windows_fonts / "yahei.ttf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"font")
    yahei = replace(fake_face(cps("ab"), path=str(path), family="Microsoft YaHei"), local_names=("微软雅黑",))
    a, b = faces
    model.set_catalog({a.key: a, b.key: b, yahei.key: yahei})
    model.set_family("微软雅黑")
    assert controller.conflict() == ("block", "Windows already has a font called “微软雅黑” — choose another name.")


def test_the_registered_font_decides_when_the_catalog_does_not_know_it(controller, installer, tmp_path):
    registered = tmp_path / "user" / STAGED
    installer.registered[FULL] = registered
    installer.forged.add(str(registered))
    assert controller.conflict() == ("none", "")               # registered, but the file is gone
    registered.parent.mkdir(parents=True)
    registered.write_bytes(b"font")
    assert controller.conflict() == ("replace", "Replace the “Test Mix Regular” you installed earlier?")
    installer.forged.clear()
    assert controller.conflict() == ("block",
                                     "You already have a font called “Test Mix Regular” installed — choose another name.")
    installer.lookup_error = InstallNotSupported("not here")
    assert controller.conflict() == ("none", "")
    installer.lookup_error = OSError("registry unreadable")
    assert controller.conflict() == ("none", "")


# ----- reset ----------------------------------------------------------------------------------------------
def test_reset_forgets_everything(qtbot, controller, model, forge_calls):
    _install(qtbot, controller)
    controller.uninstall()
    _install(qtbot, controller)
    controller.reset()
    assert controller.state is BuildState.IDLE
    for attr in ("intent", "installed_name", "installed_path", "saved_path", "error", "error_detail", "report",
                 "notice"):
        assert getattr(controller, attr) is None, attr
    assert controller.stage == "" and controller.fraction == 0.0 and not controller.is_update()


def test_start_over_during_a_build_stays_idle_when_the_cancel_lands(qtbot, controller, model, forge_waits_for_cancel):
    controller.install()
    assert controller.state is BuildState.BUILDING
    with qtbot.waitSignal(model.resultCancelled, timeout=15000):
        model.reset()                                          # emits resetDone: the controller resets too
        assert controller.state is BuildState.IDLE
    assert controller.state is BuildState.IDLE
