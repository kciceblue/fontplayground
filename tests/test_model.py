import os
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest

from fontplayground.catalog.face import read_faces
from fontplayground.engine.scripts import GROUP_IDS
from fontplayground.engine.spec import ForgeError, ForgeReport, Plan
from fontplayground.ui import model as model_module
from fontplayground.ui import workers
from fontplayground.ui.model import (EMPTY_ERROR, GLYPH_NEAR_TEXT, ForgeModel, MaterialRow, clean_stale_results,
                                     glyph_limit_text, stage_text)
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
    bad = replace(c, family="Fixture Z", outline="CFF2")  # a real file (fixture C) that the engine cannot use
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


def test_missing_sample_chars_never_count_invisible_characters(model, faces):
    a, b, c = faces
    # a zero-width joiner, a variation selector, a zero-width space, a soft hyphen and a bidi control
    model.set_sample_text("a\u200d b\ufe0f\u200b\u00ad漢\u202a\n")
    assert model.missing_sample_chars() == ["a", "b", "漢"]
    model.add(a)
    assert model.missing_sample_chars() == ["漢"]
    model.set_sample_text("\u200d\ufe0f \t")
    assert model.missing_sample_chars() == []


def test_suggestions_pass_the_glyphs_the_tray_already_needs(model, faces):
    a, b, c = faces
    model.set_sample_text("a b漢 →→Ω")
    main = replace(a, glyph_count=57_535)      # Main counts in full
    big_c = replace(c, glyph_count=10_000)     # 10,000 × 0.8 + 57,535 = 65,535: still allowed next to Main alone
    sym = fake_face(cps("→"), path="sym.ttf", family="Sym")
    model.add(main)
    model.set_catalog({main.key: main, b.key: b, big_c.key: big_c, sym.key: sym})
    model.recompute_plan_now()
    # C covers two of Ω → 漢; Sym (2 glyphs) and B (5 glyphs) cover one each: fewer glyphs first
    assert [f.family for f in model.suggestions()] == ["Fixture C", "Sym", "Fixture B"]
    model.add(b)                               # supplies 漢 and ，: two more glyphs are needed, so C would pass the limit
    model.recompute_plan_now()
    assert model.missing_sample_chars() == ["Ω", "→"]
    assert [f.family for f in model.suggestions()] == ["Sym", "Fixture C"]


def test_set_catalog_refreshes_changed_faces_and_drops_vanished_ones(qtbot, model, faces, slow_fake_forge):
    a, b, c = faces
    model.add(a)
    model.add(b)
    model.set_pin("han", b.key)
    model.set_base(b.key)
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()
    try:
        same = replace(a)  # a rescan that found the same font: equal by value, another object
        with qtbot.waitSignal(model.materialsChanged):
            model.set_catalog({same.key: same, b.key: b, c.key: c})
        assert model.main is a and not model.is_stale             # nothing differed: not an edit
        assert model.catalog == {same.key: same, b.key: b, c.key: c}
        rescanned = replace(a, mtime=a.mtime + 1)
        with qtbot.waitSignal(model.resultStale):
            model.set_catalog({rescanned.key: rescanned, b.key: b})
        assert model.main is rescanned and model.is_stale and model.keys() == [a.key, b.key]
        # the catalog after a scan is complete: a material whose font is gone leaves the tray with its pins
        assert model.family == "Fixture A Fixture B"
        model.set_catalog({rescanned.key: rescanned, c.key: c})
        assert model.keys() == [a.key] and model.pins["han"] is None and model.base_key is None
        assert model.family == "Fixture A Forged"
    finally:
        _cleanup_result(model)


def test_validity_flags_a_font_file_that_vanished(model, font_dir, tmp_path):
    copy = tmp_path / "gone.ttf"
    shutil.copyfile(font_dir / "A.ttf", copy)
    (face,) = read_faces(copy)
    model.add(face)
    assert model.validity() == ""
    copy.unlink()
    model.recompute_plan_now()  # the next check (any change, or the plan) notices
    assert model.validity() == "Fixture A Regular: the font file is no longer there"
    assert model.combine() is False


# ----- glyph budget ------------------------------------------------------------------------------
def test_glyph_budget_warns_near_the_limit_and_blocks_past_it(qtbot, model, faces):
    a, b, c = faces
    seen = []
    model.validityChanged.connect(seen.append)
    assert model.glyph_estimate() == 0 and model.glyph_warning() == ""
    main = replace(a, glyph_count=60_000)                # its 5 characters all come from Main: 1 + 60,000 × 0.8
    with qtbot.waitSignal(model.planChanged, timeout=2000):
        model.add(main)
    assert model.glyph_estimate() == 48_001 and model.glyph_warning() == "" and model.validity() == ""
    near = replace(b, glyph_count=40_000)                # supplies 漢 and ，, half its map: 40,000 × 0.5 × 0.8
    model.add(near)
    model.recompute_plan_now()
    assert model.glyph_estimate() == 64_001
    assert model.glyph_warning() == GLYPH_NEAR_TEXT == ("These fonts come close to the 65,535-glyph limit; if forging "
                                                        "fails, remove a font or use a smaller build.")
    assert model.validity() == "" and seen == [""]       # a warning, not a problem
    model.remove(near.key)
    model.add(replace(b, glyph_count=45_000))            # 18,000 more: 66,001
    model.recompute_plan_now()
    text = ("Together these fonts need about 66,001 glyphs; a font can hold 65,535. "
            "Remove a font or use a smaller (regional) build.")
    assert model.glyph_estimate() == 66_001 and glyph_limit_text(66_001) == text
    assert model.validity() == text == model.glyph_warning() == seen[-1]
    assert model.combine() is False                      # Next: Forge stays disabled
    with qtbot.waitSignal(model.validityChanged, timeout=2000):
        model.remove(b.key)                              # the debounced plan lifts it
    assert model.validity() == "" and model.glyph_estimate() == 48_001 and model.glyph_warning() == ""
    model.remove(main.key)
    assert model.recompute_plan_now() is None and model.glyph_estimate() == 0 and model.glyph_warning() == ""


# ----- reset -------------------------------------------------------------------------------------
def test_reset_starts_over_but_keeps_the_sample_text_and_the_catalog(qtbot, model, faces, slow_fake_forge):
    a, b, c = faces
    catalog = {f.key: f for f in (a, b, c)}
    model.set_catalog(catalog)
    model.add(a)
    model.add(b)
    model.set_base(b.key)
    model.set_pin("latin", b.key)
    model.set_adjust(a.key, 500, 1.2)
    model.set_defaults(700, 0.9)
    model.set_family("Mine")
    model.set_style("Heavy")
    model.set_output("D:/out/x.ttf")
    model.set_sample_text("keep me")
    with qtbot.waitSignal(model.resultReady, timeout=10000):
        model.combine()
    model.set_defaults(600, 0.9)
    assert model.is_stale and model.result_path is not None
    signals = []
    for name in ("materialsChanged", "namesChanged", "resetDone", "sampleChanged"):
        getattr(model, name).connect(lambda *args, n=name: signals.append(n))
    model.planChanged.connect(lambda p: signals.append(("plan", p)))
    model.validityChanged.connect(lambda t: signals.append(("validity", t)))
    model.reset()
    assert signals == ["materialsChanged", "namesChanged", ("plan", None), ("validity", EMPTY_ERROR), "resetDone"]
    assert model.rows == [] and model.main is None and model.base_key is None and model.base is None
    assert model.pins == {g: None for g in GROUP_IDS}
    assert (model.default_weight, model.default_scale) == (None, 1.0)
    docs = Path.home() / "Documents"
    assert (model.family, model.style, model.output) == ("Forged", "Regular", str(docs / "Forged-Regular.ttf"))
    assert model.names_edited == {"family": False, "style": False, "output": False}
    assert model.result_path is None and model.result_report is None and not model.is_stale and not model.is_busy()
    assert model.plan is None and model.glyph_estimate() == 0 and model.validity() == EMPTY_ERROR
    assert model.sample_text == "keep me" and model.catalog == catalog
    qtbot.wait(300)
    assert signals[-1] == "resetDone"  # no pending plan fires afterwards
    model.add(c)
    assert (model.family, model.style) == ("Fixture C Forged", "Regular")  # proposed again, not "Mine"


def test_reset_cancels_a_running_combine(qtbot, model, faces, forge_waits_for_cancel):
    a, b, c = faces
    model.add(a)
    model.combine()
    worker = model.worker
    with qtbot.waitSignal(model.resultCancelled, timeout=15000):
        model.reset()
    qtbot.waitUntil(lambda: not model.is_busy(), timeout=15000)
    assert model.rows == [] and model.result_path is None and not os.path.exists(worker.output_path)


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


def test_from_settings_skips_malformed_entries_and_defaults_the_rest(model, faces):
    a, b, c = faces
    catalog = {f.key: f for f in (a, b, c)}
    d = {
        "materials": [
            {"path": a.path, "index": "0"},                         # an index given as a string still finds the font
            "junk",                                                 # not a material
            {"path": b.path, "index": "zero"},                      # an index that is not a number: skipped
            {"path": 5, "index": 0},                                # a path that is not a string: skipped
            {"path": c.path, "index": c.index, "weight": "700", "scale": "big"},
        ],
        "base_index": "4",                                          # counts the skipped entries, like a vanished font
        "script_rules": "nope",
        "default_weight": "500",
        "default_scale": "wide",
        "pins": {"latin": a.path,                                   # a pin given as a string
                 "han": [a.path],                                   # too short
                 "hangul": [a.path, "0"],                           # a stored index as a string: fine
                 "kana": None, "bogus": [a.path, 0], "greek": 7},
        "family_name": "Typed", "style_name": 12, "output_path": ["not", "a", "path"],
        "names_edited": "yes",                                      # not a dict: the old-file heuristic applies
        "sample_text": 5,
    }
    model.from_settings(d, catalog)
    assert model.keys() == [a.key, c.key]
    assert model.row(c.key).weight == 700 and model.row(c.key).scale is None
    assert model.base_key == c.key and (model.default_weight, model.default_scale) == (500, 1.0)
    assert model.pins["hangul"] == a.key and model.pins["latin"] is None and model.pins["han"] is None
    assert model.pins["kana"] is None and model.pins["greek"] is None and "bogus" not in model.pins
    assert model.family == "Typed" and model.names_edited["family"]
    assert model.style == "Regular" and not model.names_edited["style"]
    assert model.output == str(Path.home() / "Documents" / "Typed-Regular.ttf") and not model.names_edited["output"]
    assert model.sample_text == DEFAULT_SAMPLE and model.validity() == ""


@pytest.mark.parametrize("bad", [
    None, "text", [], {"materials": "not a list"}, {"materials": {"path": "x", "index": 0}}, {"materials": [None, 3]},
    {"materials": None, "pins": "latin", "names_edited": [], "script_rules": [1, 2], "base_index": None},
    {"base_index": -3, "default_scale": float("nan"), "default_weight": True, "family_name": None},
])
def test_from_settings_never_raises_on_malformed_input(model, faces, bad):
    a, b, c = faces
    model.add(b)
    model.from_settings(bad, {f.key: f for f in (a, b, c)})
    assert model.keys() == [] and model.validity() == EMPTY_ERROR and model.pins == {g: None for g in GROUP_IDS}
    assert (model.family, model.style) == ("Forged", "Regular")
    assert (model.default_weight, model.default_scale) == (None, 1.0)


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
    broken = tmp_path / "broken.ttf"
    broken.write_bytes(b"not a font")  # on disk, so the spec is valid, but unreadable
    ghost = fake_face(cps("ab"), path=str(broken), family="Ghost")
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
