import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from fontplayground.catalog.face import read_faces
from fontplayground.engine.spec import ForgeError, ForgeReport, Plan
from fontplayground.ui import model as model_module
from fontplayground.ui import workers
from fontplayground.ui.model import EMPTY_ERROR, ForgeModel, MaterialRow, clean_stale_results, stage_text
from fontplayground.ui.preview import DEFAULT_SAMPLE
from tests.fixtures import cps, fake_face


@pytest.fixture
def faces(font_dir):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    (c,) = read_faces(font_dir / "C.ttf")
    return a, b, c


@pytest.fixture
def model(qapp):
    return ForgeModel()


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
def slow_fake_forge(monkeypatch):
    """A forge() that writes a stub file after 300 ms so a test can change the model while it 'runs'."""
    def fake_forge(spec, output_path, progress=None):
        time.sleep(0.3)
        Path(output_path).write_bytes(b"stub")
        return ForgeReport([], 0, 0, [], str(output_path))
    monkeypatch.setattr(workers, "forge", fake_forge)


def _cleanup_result(model: ForgeModel) -> None:
    # discard_result() unloads the font and deletes the temp file, ignoring errors: Qt's offscreen
    # font database on Windows keeps the file mapped, so the unlink may fail there. Best effort only.
    path = model.result_path
    model.discard_result()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def _keys(model):
    return [k[0].rsplit(os.sep, 1)[-1] for k in model.keys()]


# ----- materials ---------------------------------------------------------------------------------
def test_add_remove_move_and_set_order(qtbot, model, faces):
    a, b, c = faces
    changes = []
    model.materialsChanged.connect(lambda: changes.append(1))
    assert model.add(a) and model.add(b) and model.add(c)
    assert not model.add(a)  # already there
    assert _keys(model) == ["A.ttf", "B.otf", "C.ttf"] and len(changes) == 3
    assert model.main is a and model.rows[1] == MaterialRow(b) and model.has(b.key) and model.index_of(c.key) == 2

    assert model.move(c.key, 0) and _keys(model) == ["C.ttf", "A.ttf", "B.otf"]
    assert not model.move(c.key, 0) and not model.move(("nope", 0), 1)
    assert model.move(c.key, 99) and _keys(model) == ["A.ttf", "B.otf", "C.ttf"]  # clamped to the end

    assert model.set_order([b.key, ("nope", 0), a.key]) and _keys(model) == ["B.otf", "A.ttf", "C.ttf"]
    assert not model.set_order([b.key, a.key, c.key])  # unchanged
    assert model.set_order([list(c.key)]) and _keys(model) == ["C.ttf", "B.otf", "A.ttf"]  # keys may be lists

    assert model.remove(b.key) and _keys(model) == ["C.ttf", "A.ttf"]
    assert not model.remove(b.key)
    assert model.row(b.key) is None and model.row(a.key).face is a


def test_remove_clears_base_and_pins_that_pointed_to_it(model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    assert model.set_base(b.key) and model.base_key == b.key and model.base is b and model.base_index() == 1
    assert model.set_pin("latin", b.key) and model.pins["latin"] == b.key
    assert model.set_pin("han", a.key)
    model.remove(b.key)
    assert model.base_key is None and model.base is a and model.base_index() == 0
    assert model.pins["latin"] is None and model.pins["han"] == a.key
    model.remove(a.key)
    assert model.base is None and model.base_index() is None and model.main is None


def test_pins_base_adjust_and_defaults(qtbot, model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    assert not model.set_pin("no-such-group", a.key)
    assert not model.set_pin("latin", None)                       # already automatic
    assert model.set_pin("latin", b.key) and not model.set_pin("latin", b.key)
    assert model.set_pin("han", ("missing.ttf", 0)) is False       # an unknown key means "automatic": no change
    assert model.set_pin("latin", ("missing.ttf", 0)) and model.pins["latin"] is None
    assert model.set_adjust(b.key, 500, 1.2) and model.row(b.key) == MaterialRow(b, 500, 1.2)
    assert not model.set_adjust(b.key, 500, 1.2) and not model.set_adjust(("x", 0), 1, 1.0)
    assert not model.set_base(("missing.ttf", 0))                  # unknown -> None, which it already is
    assert model.set_base(a.key) and model.base_key == a.key       # explicit Main is a real pin
    assert model.set_defaults(700, 0.9) and (model.default_weight, model.default_scale) == (700, 0.9)
    assert not model.set_defaults(700, 0.9)
    with qtbot.waitSignal(model.materialsChanged):
        model.set_defaults(None, 1.0)


def test_build_spec_reflects_rows_rules_and_names(model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.set_adjust(a.key, 300, None)
    model.set_base(b.key)
    model.set_pin("latin", b.key)
    model.set_defaults(600, 1.1)
    model.set_family("Mixed")
    model.set_style("Italic")
    spec = model.build_spec()
    assert [m.face for m in spec.materials] == [a, b]
    assert (spec.materials[0].weight, spec.materials[0].scale) == (300, None)
    assert spec.base_index == 1
    assert spec.script_rules["latin"] == 1     # pinned
    assert spec.script_rules["han"] == 1       # smart: only B has Han
    assert spec.script_rules["hangul"] is None
    assert (spec.default_weight, spec.default_scale) == (600, 1.1)
    assert (spec.family_name, spec.style_name) == ("Mixed", "Italic")
    assert spec.validate() == []
    model.set_order([b.key, a.key])
    assert model.build_spec().base_index == 0 and model.build_spec().script_rules["latin"] == 0


def test_validity_wording_and_signal(qtbot, model, faces):
    a, b, c = faces
    seen = []
    model.validityChanged.connect(seen.append)
    assert model.validity() == EMPTY_ERROR == "Add at least one font."
    model.add(a)
    assert model.validity() == "" and seen == [""]
    model.set_family("   ")
    assert model.validity() == "Family name is empty." == seen[-1]
    model.set_family("Ok")
    assert model.validity() == ""
    model.set_style("")
    assert model.validity() == "Style name is empty."
    model.set_style("Regular")
    bad = fake_face(cps("ab"), path="cff2.otf", family="Fixture Z", outline="CFF2")
    model.add(bad)
    assert model.validity() == "Fixture Z Regular: CFF2 outlines are not supported"
    model.remove(bad.key)
    model.set_adjust(a.key, None, 50.0)
    assert model.validity().startswith("Fixture A Regular: scale 50 must be between")
    model.remove(a.key)
    assert model.validity() == EMPTY_ERROR and seen[-1] == EMPTY_ERROR


# ----- plan --------------------------------------------------------------------------------------
def test_plan_is_debounced_and_recompute_now_is_immediate(qtbot, model, faces):
    a, b, c = faces
    plans = []
    model.planChanged.connect(plans.append)
    assert model.plan is None
    with qtbot.waitSignal(model.planChanged, timeout=2000):
        model.add(a)
        model.add(b)          # two quick changes: one plan
        assert model.plan is None
    assert len(plans) == 1 and isinstance(model.plan, Plan) and len(model.plan.source) == 7
    qtbot.wait(300)
    assert len(plans) == 1
    model.set_pin("latin", b.key)
    got = model.recompute_plan_now()
    assert got is model.plan and len(plans) == 2
    assert model.plan.source[ord("a")] == 1  # Latin now comes from B
    qtbot.wait(300)
    assert len(plans) == 2                   # recompute_plan_now cancels the pending debounce
    model.remove(a.key)
    model.remove(b.key)
    assert model.recompute_plan_now() is None and plans[-1] is None


# ----- names -------------------------------------------------------------------------------------
def test_names_are_proposed_until_the_user_edits_them(qtbot, model, faces):
    a, b, c = faces
    names = []
    model.namesChanged.connect(lambda: names.append((model.family, model.style, model.output)))
    docs = Path.home() / "Documents"
    assert (model.family, model.style) == ("Forged", "Regular") and model.output == str(docs / "Forged-Regular.ttf")
    model.add(b)
    assert (model.family, model.style) == ("Fixture B Forged", "Bold")
    assert model.output == str(docs / "Fixture B Forged-Bold.ttf") and len(names) == 1
    model.add(a)
    assert model.family == "Fixture B Fixture A" and model.output == str(docs / "Fixture B Fixture A-Bold.ttf")
    model.set_order([a.key, b.key])
    assert (model.family, model.style) == ("Fixture A Fixture B", "Regular")
    assert model.names_edited == {"family": False, "style": False, "output": False}

    with qtbot.waitSignal(model.namesChanged):
        model.set_family("Mine")
    assert model.names_edited["family"] and model.output == str(docs / "Mine-Regular.ttf")
    model.add(c)
    assert model.family == "Mine" and model.output == str(docs / "Mine-Regular.ttf")  # kept
    model.set_style("Heavy", by_user=False)
    assert model.style == "Heavy" and not model.names_edited["style"]
    assert model.output == str(docs / "Mine-Heavy.ttf")
    model.set_order([b.key, a.key, c.key])
    assert model.style == "Bold"  # not edited by the user: proposed again
    model.set_output("D:/out/x.ttf")
    model.set_style("Custom")
    assert model.output == "D:/out/x.ttf" and model.names_edited == {"family": True, "style": True, "output": True}
    model.remove(a.key)
    assert (model.family, model.style, model.output) == ("Mine", "Custom", "D:/out/x.ttf")


def test_sample_text_missing_chars_and_suggestions(qtbot, model, faces):
    a, b, c = faces
    assert model.sample_text == DEFAULT_SAMPLE
    with qtbot.waitSignal(model.sampleChanged) as blocker:
        model.set_sample_text("a b漢 →→Ω")
    assert blocker.args == ["a b漢 →→Ω"]
    with qtbot.assertNotEmitted(model.sampleChanged):
        model.set_sample_text("a b漢 →→Ω")
    assert model.missing_sample_chars() == ["a", "b", "Ω", "→", "漢"]  # no fonts: everything is missing (code point order)
    model.add(a)
    assert model.missing_sample_chars() == ["Ω", "→", "漢"]
    assert model.suggestions() == []  # no catalog yet
    model.set_catalog({f.key: f for f in (a, b, c)})
    assert [f.family for f in model.suggestions()] == ["Fixture C", "Fixture B"]  # C covers two, B one
    assert [f.family for f in model.suggestions(limit=1)] == ["Fixture C"]
    model.add(c)
    assert model.missing_sample_chars() == ["漢"]
    assert [f.family for f in model.suggestions()] == ["Fixture B"]
    model.add(b)
    assert model.missing_sample_chars() == [] and model.suggestions() == []


def test_set_catalog_refreshes_faces_after_a_rescan(qtbot, model, faces):
    a, b, c = faces
    model.add(a)
    rescanned = replace(a, mtime=a.mtime + 1)
    with qtbot.waitSignal(model.materialsChanged):
        model.set_catalog({rescanned.key: rescanned, b.key: b})
    assert model.main is rescanned and model.catalog == {rescanned.key: rescanned, b.key: b}
    with qtbot.assertNotEmitted(model.materialsChanged):
        model.set_catalog({rescanned.key: rescanned})  # same objects: nothing to do


# ----- settings ----------------------------------------------------------------------------------
def test_settings_round_trip(model, faces):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.add(c)
    model.set_order([b.key, c.key, a.key])
    model.set_base(c.key)
    model.set_pin("latin", a.key)
    model.set_adjust(a.key, 500, None)
    model.set_adjust(c.key, None, 0.8)
    model.set_defaults(400, 1.05)
    model.set_family("Round Trip")
    model.set_sample_text("abc")
    d = model.to_settings()
    assert set(d) >= {"materials", "base_index", "script_rules", "default_weight", "default_scale", "family_name",
                      "style_name", "output_path", "pins", "names_edited", "sample_text"}
    assert [m["path"] for m in d["materials"]] == [b.path, c.path, a.path]
    assert d["base_index"] == 1 and d["pins"]["latin"] == [a.path, a.index] and d["pins"]["han"] is None
    assert d["script_rules"]["latin"] == 2 and d["script_rules"]["han"] == 0
    assert d["names_edited"] == {"family": True, "style": False, "output": False} and d["sample_text"] == "abc"

    other = ForgeModel()
    other.from_settings(d, {f.key: f for f in (a, b, c)})
    assert other.keys() == [b.key, c.key, a.key]
    assert other.base_key == c.key and other.pins["latin"] == a.key and other.pins["han"] is None
    assert other.row(a.key).weight == 500 and other.row(c.key).scale == 0.8
    assert (other.default_weight, other.default_scale) == (400, 1.05)
    assert (other.family, other.style) == ("Round Trip", "Bold") and other.names_edited == d["names_edited"]
    assert other.output == str(Path.home() / "Documents" / "Round Trip-Bold.ttf")
    assert other.sample_text == "abc" and other.validity() == ""
    assert other.to_settings() == d

    dropped = ForgeModel()
    dropped.from_settings(d, {f.key: f for f in (a, b)})  # C is gone from the catalog
    assert dropped.keys() == [b.key, a.key]
    assert dropped.base_key is None and dropped.pins["latin"] == a.key


def test_from_settings_reads_the_old_schema(model, faces):
    a, b, c = faces
    old = {"materials": [{"path": a.path, "index": a.index, "weight": None, "scale": None},
                         {"path": b.path, "index": b.index, "weight": None, "scale": None}],
           "base_index": 0, "script_rules": {"han": 0, "latin": None},
           "default_weight": None, "default_scale": 1.0,
           "family_name": "Typed By Hand", "style_name": "Regular", "output_path": None}
    model.from_settings(old, {a.key: a, b.key: b})
    assert model.pins["han"] == a.key and model.pins["latin"] is None  # explicit rules were pins
    assert model.family == "Typed By Hand" and model.names_edited["family"]
    assert model.style == "Regular" and not model.names_edited["style"]   # equal to the proposal: not an edit
    assert model.output == str(Path.home() / "Documents" / "Typed By Hand-Regular.ttf")
    assert not model.names_edited["output"]


def test_from_settings_emits_the_signals_pages_rely_on(qtbot, model, faces):
    a, b, c = faces
    d = {"materials": [{"path": a.path, "index": a.index}], "sample_text": "zz"}
    with qtbot.waitSignals([model.materialsChanged, model.namesChanged, model.sampleChanged, model.validityChanged,
                            model.planChanged], timeout=2000):
        model.from_settings(d, {a.key: a})
    assert model.keys() == [a.key] and model.sample_text == "zz" and model.validity() == ""


# ----- combine -----------------------------------------------------------------------------------
def test_stage_text_is_plain_language():
    assert stage_text("plan") == "Deciding which font supplies each character…"
    assert stage_text("prepare:Fixture A Regular") == "Preparing Fixture A Regular…"
    assert stage_text("merge") == "Combining the fonts…"
    assert stage_text("done") == "Done."
    assert stage_text("something new") == "something new"


def test_combine_end_to_end_then_stale_after_a_change(qtbot, model, faces, tmp_path):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.set_family("Forged Test")
    busy, stages, stale = [], [], []
    model.busyChanged.connect(busy.append)
    model.progress.connect(lambda text, fraction: stages.append(text))
    model.resultStale.connect(lambda: stale.append(1))
    assert not model.is_busy() and not model.is_stale
    with qtbot.waitSignal(model.resultReady, timeout=60000) as blocker:
        assert model.combine() is True
        assert model.is_busy() and busy == [True]
        assert model.combine() is False  # already running
    try:
        report = blocker.args[0]
        assert report is model.result_report and report.total_codepoints == 7
        assert model.result_path == report.output_path and os.path.exists(model.result_path)
        assert Path(model.result_path).parent == model_module.RESULT_DIR
        assert Path(model.result_path).name.startswith("forged-")
        assert busy == [True, False] and not model.is_busy() and not model.is_stale
        assert stages[0] == "Starting…" and "Preparing Fixture A Regular…" in stages and stages[-1] == "Done."
        assert not any(s.startswith("prepare:") for s in stages)

        out = tmp_path / "saved" / "out.ttf"
        assert model.save_to(str(out)) == out
        assert out.is_file() and out.stat().st_size == Path(model.result_path).stat().st_size
        assert read_faces(out)[0].family == "Forged Test"

        model.set_sample_text("still fresh")   # the sample is not part of the result
        model.set_output(str(tmp_path / "elsewhere.ttf"))
        assert not model.is_stale and stale == []
        with qtbot.waitSignal(model.resultStale):
            model.set_adjust(b.key, 600, None)
        assert model.is_stale and stale == [1]
        model.set_family("Again")               # only the first change announces it
        assert stale == [1]
    finally:
        _cleanup_result(model)
    assert model.result_path is None and model.result_report is None and not model.is_stale
    with pytest.raises(RuntimeError):
        model.save_to(str(tmp_path / "nothing.ttf"))


def test_names_make_the_result_stale_but_the_output_path_does_not(qtbot, model, faces, slow_fake_forge):
    a, b, c = faces
    model.add(a)
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()
    try:
        model.set_output("D:/somewhere.ttf")
        assert not model.is_stale
        model.set_family(model.family)  # the same text: the edited flag flips but nothing changed
        assert not model.is_stale
        with qtbot.waitSignal(model.resultStale):
            model.set_style("Other")
        assert model.is_stale
    finally:
        _cleanup_result(model)


def test_changes_during_a_combine_mark_the_result_stale_on_arrival(qtbot, model, faces, slow_fake_forge):
    a, b, c = faces
    model.add(a)
    stale = []
    model.resultStale.connect(lambda: stale.append(1))
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()
        model.set_defaults(700, 1.0)
        assert stale == []  # nothing to be stale yet
    try:
        assert model.is_stale and stale == [1]
    finally:
        _cleanup_result(model)


def test_combine_refuses_an_invalid_spec_and_discards_the_previous_result(qtbot, model, faces, slow_fake_forge):
    a, b, c = faces
    assert model.combine() is False and model.worker is None and not model.is_busy()
    model.add(a)
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()
    first = model.result_path
    try:
        with qtbot.waitSignal(model.resultReady, timeout=10000):
            model.combine()
        assert model.result_path != first and not os.path.exists(first)
    finally:
        _cleanup_result(model)


def test_combine_failure_emits_result_failed(qtbot, model, tmp_path):
    ghost = fake_face(cps("ab"), path=str(tmp_path / "missing.ttf"), family="Ghost")
    model.add(ghost)
    with qtbot.waitSignal(model.resultFailed, timeout=60000) as blocker:
        assert model.combine()
    message = blocker.args[0]
    assert message.startswith("[prepare (Ghost Regular)] ")
    assert "Traceback (most recent call last):" in message
    assert model.result_path is None and not model.is_busy()


def test_cancel_emits_result_cancelled_and_leaves_no_file(qtbot, model, faces, forge_waits_for_cancel):
    a, b, c = faces
    assert model.cancel() is False  # nothing running
    model.add(a)
    busy = []
    model.busyChanged.connect(busy.append)
    model.combine()
    worker = model.worker
    with qtbot.waitSignal(model.resultCancelled, timeout=15000):
        assert model.cancel() is True
    qtbot.waitUntil(lambda: not model.is_busy() and busy == [True, False], timeout=15000)
    assert model.result_path is None and not os.path.exists(worker.output_path)
    with qtbot.assertNotEmitted(model.resultFailed):
        qtbot.wait(50)


def test_cancel_can_block_until_the_worker_has_stopped(qtbot, model, faces, forge_waits_for_cancel):
    a, b, c = faces
    model.add(a)
    model.combine()
    assert model.cancel(wait_ms=15000) is True
    assert not model.worker.isRunning()
    qtbot.waitUntil(lambda: not model.is_busy(), timeout=5000)  # the queued `cancelled` still lands afterwards


def test_clean_stale_results_removes_only_forged_files(tmp_path, monkeypatch):
    fake_dir = tmp_path / "fontplayground"
    monkeypatch.setattr(model_module, "RESULT_DIR", fake_dir)
    clean_stale_results()  # no folder yet: nothing to do, no error
    fake_dir.mkdir()
    stale = fake_dir / "forged-deadbeef.ttf"
    stale.write_bytes(b"x")
    other = fake_dir / "keep.txt"
    other.write_bytes(b"y")
    clean_stale_results()
    assert not stale.exists() and other.exists()
