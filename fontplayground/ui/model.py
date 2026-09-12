"""ForgeModel: the single source of truth for the forge state.

Pages and the tray never keep their own copy of the materials, rules or names; they read the model and
react to its signals. The model proposes every setting (via ui.smart) until the user overrides it, keeps
the plan fresh on a short debounce, and owns the combine lifecycle (worker, temp result, save, stale).
"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from fontplayground.catalog.face import FontFace
from fontplayground.engine.planner import plan as plan_spec
from fontplayground.engine.scripts import GROUP_IDS
from fontplayground.engine.spec import ForgeSpec, MaterialSpec, Plan
from fontplayground.ui import smart
from fontplayground.ui.preview import DEFAULT_SAMPLE, font_loader
from fontplayground.ui.workers import CombineWorker

FaceKey = tuple[str, int]

PLAN_DEBOUNCE_MS = 150
RESULT_DIR = Path(tempfile.gettempdir()) / "fontplayground"   # combine results live here until saved or discarded
RESULT_GLOB = "forged-*.ttf"
EMPTY_ERROR = "Add at least one font."
NAME_FIELDS = ("family", "style", "output")

STAGE_TEXT = {
    "plan": "Deciding which font supplies each character…",
    "merge": "Combining the fonts…",
    "finish": "Finishing the font…",
    "verify": "Checking the result…",
    "done": "Done.",
}


def stage_text(stage: str) -> str:
    """Plain-language wording for a forge progress stage ("prepare:<font>" -> "Preparing <font>…")."""
    if stage.startswith("prepare:"):
        return f"Preparing {stage[len('prepare:'):]}…"
    return STAGE_TEXT.get(stage, stage)


def clean_stale_results() -> None:
    """Delete results left behind by earlier runs (a crash, or a quit while a combine was still running)."""
    try:
        stale = list(RESULT_DIR.glob(RESULT_GLOB))
    except OSError:
        return
    for path in stale:
        try:
            path.unlink()
        except OSError:
            pass


@dataclass
class MaterialRow:
    face: FontFace
    weight: int | None = None   # None -> the model's default weight
    scale: float | None = None  # None -> the model's default scale


class ForgeModel(QObject):
    materialsChanged = Signal()        # rows, order, base, pins, adjustments or defaults changed
    planChanged = Signal(object)       # Plan | None, after the debounce
    validityChanged = Signal(str)      # first problem with the spec, "" when it is valid
    sampleChanged = Signal(str)
    busyChanged = Signal(bool)
    progress = Signal(str, float)      # plain-language stage text, fraction 0..1
    resultReady = Signal(object)       # ForgeReport
    resultFailed = Signal(str)         # first line: the error; the rest: the full traceback
    resultCancelled = Signal()
    resultStale = Signal()             # something changed after a result was produced
    namesChanged = Signal()            # family, style or output path changed (by the user or automatically)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[MaterialRow] = []
        self._base_key: FaceKey | None = None                  # None -> Main
        self._pins: dict[str, FaceKey | None] = {g: None for g in GROUP_IDS}
        self._default_weight: int | None = None                # None -> "As is"
        self._default_scale = 1.0
        self._family = smart.default_family_name([])
        self._style = smart.default_style(None)
        self._output = str(smart.default_output_path(self._family, self._style))
        self._edited = {name: False for name in NAME_FIELDS}
        self._sample_text = DEFAULT_SAMPLE
        self._catalog: dict[FaceKey, FontFace] = {}
        self._plan: Plan | None = None
        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.setInterval(PLAN_DEBOUNCE_MS)
        self._plan_timer.timeout.connect(self.recompute_plan_now)
        self._validity = self._compute_validity()
        self._serial = 0                                       # bumps on every change; combine remembers it
        self._serial_at_start = 0
        self._busy = False
        self._stale = False
        self.worker: CombineWorker | None = None
        self.result_path: str | None = None
        self.result_report = None

    # ----- reading -----
    @property
    def rows(self) -> list[MaterialRow]:
        return list(self._rows)

    def keys(self) -> list[FaceKey]:
        return [r.face.key for r in self._rows]

    def has(self, key: FaceKey) -> bool:
        return any(r.face.key == key for r in self._rows)

    def row(self, key: FaceKey) -> MaterialRow | None:
        return next((r for r in self._rows if r.face.key == key), None)

    def index_of(self, key: FaceKey | None) -> int | None:
        return next((i for i, r in enumerate(self._rows) if r.face.key == key), None)

    @property
    def main(self) -> FontFace | None:
        return self._rows[0].face if self._rows else None

    @property
    def base_key(self) -> FaceKey | None:
        """The pinned base (line spacing) key, or None when the base follows Main."""
        return self._base_key

    @property
    def base(self) -> FontFace | None:
        i = self.base_index()
        return self._rows[i].face if i is not None else None

    def base_index(self) -> int | None:
        if not self._rows:
            return None
        i = self.index_of(self._base_key) if self._base_key is not None else None
        return i if i is not None else 0

    @property
    def pins(self) -> dict[str, FaceKey | None]:
        return dict(self._pins)

    @property
    def default_weight(self) -> int | None:
        return self._default_weight

    @property
    def default_scale(self) -> float:
        return self._default_scale

    @property
    def family(self) -> str:
        return self._family

    @property
    def style(self) -> str:
        return self._style

    @property
    def output(self) -> str:
        return self._output

    @property
    def names_edited(self) -> dict[str, bool]:
        return dict(self._edited)

    @property
    def sample_text(self) -> str:
        return self._sample_text

    @property
    def catalog(self) -> dict[FaceKey, FontFace]:
        return self._catalog

    @property
    def plan(self) -> Plan | None:
        return self._plan

    @property
    def is_stale(self) -> bool:
        return self.result_path is not None and self._stale

    def is_busy(self) -> bool:
        return self._busy

    # ----- materials -----
    def add(self, face: FontFace) -> bool:
        """Append a material (priority = order added). False when it is already in the tray."""
        if self.has(face.key):
            return False
        self._rows.append(MaterialRow(face))
        self._materials_edited()
        return True

    def remove(self, key: FaceKey) -> bool:
        i = self.index_of(key)
        if i is None:
            return False
        del self._rows[i]
        if self._base_key == key:
            self._base_key = None
        self._pins = {g: (None if k == key else k) for g, k in self._pins.items()}
        self._materials_edited()
        return True

    def move(self, key: FaceKey, new_index: int) -> bool:
        i = self.index_of(key)
        if i is None:
            return False
        new_index = max(0, min(new_index, len(self._rows) - 1))
        if new_index == i:
            return False
        row = self._rows.pop(i)
        self._rows.insert(new_index, row)
        self._materials_edited()
        return True

    def set_order(self, keys) -> bool:
        """Reorder to match `keys`; rows not listed keep their relative order after them."""
        by_key = {r.face.key: r for r in self._rows}
        wanted = [tuple(k) for k in keys]
        seen: set[FaceKey] = set()
        ordered: list[MaterialRow] = []
        for k in wanted:
            if k in by_key and k not in seen:
                ordered.append(by_key[k])
                seen.add(k)
        ordered += [r for r in self._rows if r.face.key not in seen]
        if [r.face.key for r in ordered] == self.keys():
            return False
        self._rows = ordered
        self._materials_edited()
        return True

    def set_pin(self, group_id: str, key: FaceKey | None) -> bool:
        """Pin a script group to a material (None = let the app decide). Keys not in the tray count as None."""
        if group_id not in self._pins:
            return False
        key = tuple(key) if key is not None and self.has(tuple(key)) else None
        if self._pins[group_id] == key:
            return False
        self._pins[group_id] = key
        self._inputs_edited()
        return True

    def set_adjust(self, key: FaceKey, weight: int | None, scale: float | None) -> bool:
        row = self.row(key)
        if row is None or (row.weight, row.scale) == (weight, scale):
            return False
        row.weight, row.scale = weight, scale
        self._inputs_edited()
        return True

    def set_base(self, key: FaceKey | None) -> bool:
        key = tuple(key) if key is not None and self.has(tuple(key)) else None
        if key == self._base_key:
            return False
        self._base_key = key
        self._inputs_edited()
        return True

    def set_defaults(self, weight: int | None, scale: float) -> bool:
        if (weight, scale) == (self._default_weight, self._default_scale):
            return False
        self._default_weight, self._default_scale = weight, float(scale)
        self._inputs_edited()
        return True

    def set_catalog(self, faces_by_key: dict[FaceKey, FontFace]) -> None:
        """Remember the scanned faces (for suggestions) and refresh the tray's faces from them after a rescan."""
        self._catalog = dict(faces_by_key)
        refreshed = False
        for row in self._rows:
            face = self._catalog.get(row.face.key)
            if face is not None and face is not row.face:
                row.face = face
                refreshed = True
        if refreshed:
            self._materials_edited()

    # ----- names and sample -----
    def set_family(self, text: str, by_user: bool = True) -> None:
        self._set_name("family", text, by_user)

    def set_style(self, text: str, by_user: bool = True) -> None:
        self._set_name("style", text, by_user)

    def set_output(self, path, by_user: bool = True) -> None:
        self._set_name("output", str(path), by_user)

    def set_sample_text(self, text: str) -> None:
        if text == self._sample_text:
            return
        self._sample_text = text
        self.sampleChanged.emit(text)

    def missing_sample_chars(self) -> list[str]:
        """Non-space sample characters no material covers, sorted, without duplicates."""
        covered: set[int] = set().union(*(r.face.codepoints for r in self._rows)) if self._rows else set()
        return sorted({c for c in self._sample_text if not c.isspace() and ord(c) not in covered})

    def suggestions(self, limit: int = 3) -> list[FontFace]:
        missing = {ord(c) for c in self.missing_sample_chars()}
        return smart.suggest_materials(missing, self._catalog.values(), self.main, limit=limit,
                                       exclude_keys=self.keys())

    # ----- spec, validity, plan -----
    def script_rules(self) -> dict[str, int | None]:
        keys = self.keys()
        return smart.resolve_rules(keys, self._pins, smart.group_counts(r.face for r in self._rows))

    def build_spec(self) -> ForgeSpec:
        return ForgeSpec(
            materials=[MaterialSpec(r.face, r.weight, r.scale) for r in self._rows],
            base_index=self.base_index() or 0,
            script_rules=self.script_rules(),
            default_weight=self._default_weight,
            default_scale=self._default_scale,
            family_name=self._family,
            style_name=self._style,
        )

    def validity(self) -> str:
        """"" when the spec can be forged, else the first problem in plain words."""
        return self._validity

    def recompute_plan_now(self) -> Plan | None:
        """Compute the plan immediately (the debounce timer calls this; tests may too) and emit planChanged."""
        self._plan_timer.stop()
        self._plan = plan_spec(self.build_spec()) if self._rows else None
        self.planChanged.emit(self._plan)
        return self._plan

    # ----- combine lifecycle -----
    def combine(self) -> bool:
        """Forge into a fresh temp file under RESULT_DIR. False when busy or the spec is not valid."""
        if self._busy or self._validity:
            return False
        self.discard_result()
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULT_DIR / f"forged-{uuid4().hex[:8]}.ttf"
        self._serial_at_start = self._serial
        self.worker = CombineWorker(self.build_spec(), str(out))
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self._set_busy(True)
        self.progress.emit("Starting…", 0.0)
        self.worker.start()
        return True

    def cancel(self, wait_ms: int | None = None) -> bool:
        """Ask a running combine to stop at its next stage boundary; optionally block until the thread has.

        Returns True when there was a combine to cancel; resultCancelled follows (not resultFailed).
        """
        if not self._busy or self.worker is None:
            return False
        self.worker.cancel()
        if wait_ms is not None:
            self.worker.wait(wait_ms)
        return True

    def save_to(self, path) -> Path:
        """Copy the result to `path` (folders created as needed). Raises RuntimeError when there is no result."""
        if not self.result_path or not Path(self.result_path).is_file():
            raise RuntimeError("Nothing to save")
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.result_path, dest)
        return dest

    def discard_result(self) -> None:
        """Forget the last result: unload it from Qt and delete its temp file."""
        self.result_report = None
        self._stale = False
        if self.result_path is None:
            return
        path, self.result_path = self.result_path, None
        try:
            font_loader().unload(path)
        except Exception:
            pass
        try:
            Path(path).unlink()
        except OSError:
            pass

    # ----- settings -----
    def to_settings(self) -> dict:
        d = self.build_spec().to_dict()
        d["output_path"] = self._output
        d["pins"] = {g: (list(k) if k is not None else None) for g, k in self._pins.items()}
        d["names_edited"] = dict(self._edited)
        d["sample_text"] = self._sample_text
        return d

    def from_settings(self, d: dict, faces_by_key: dict[FaceKey, FontFace]) -> None:
        """Restore a to_settings() dict; materials missing from `faces_by_key` are dropped."""
        spec = ForgeSpec.from_dict(d, faces_by_key)
        self._rows = [MaterialRow(m.face, m.weight, m.scale) for m in spec.materials]
        self._base_key = self._rows[spec.base_index].face.key if self._rows and spec.base_index > 0 else None
        self._default_weight, self._default_scale = spec.default_weight, float(spec.default_scale)
        self._pins = {g: None for g in GROUP_IDS}
        if "pins" in d:
            for g, k in (d.get("pins") or {}).items():
                if g in self._pins and k is not None and self.has((str(k[0]), int(k[1]))):
                    self._pins[g] = (str(k[0]), int(k[1]))
        else:  # older files: every explicit rule was a pin
            for g, i in spec.script_rules.items():
                if g in self._pins and i is not None and 0 <= i < len(self._rows):
                    self._pins[g] = self._rows[i].face.key
        stored = {"family": spec.family_name, "style": spec.style_name, "output": d.get("output_path")}
        auto = self._auto_names()
        edited = d.get("names_edited")
        for name in NAME_FIELDS:
            value = stored[name]
            if edited is not None:
                self._edited[name] = bool(edited.get(name, False))
            else:  # older files: a value that differs from what the app would propose was typed by the user
                self._edited[name] = value is not None and str(value) != auto[name]
            setattr(self, f"_{name}", str(value) if self._edited[name] and value is not None else auto[name])
        if self._edited["family"] or self._edited["style"]:
            if not self._edited["output"]:
                self._output = str(smart.default_output_path(self._family, self._style))
        sample = d.get("sample_text")
        if isinstance(sample, str) and sample:
            self._sample_text = sample
        self.materialsChanged.emit()
        self.namesChanged.emit()
        self.sampleChanged.emit(self._sample_text)
        self._after_change()

    # ----- internals -----
    def _materials_edited(self) -> None:
        """Rows or their order changed: re-propose the names, then the usual bookkeeping."""
        self._refresh_auto_names()
        self.materialsChanged.emit()
        self._after_change()

    def _inputs_edited(self) -> None:
        """Base, pins, adjustments or defaults changed."""
        self.materialsChanged.emit()
        self._after_change()

    def _after_change(self) -> None:
        self._serial += 1
        self._revalidate()
        self._plan_timer.start()
        self._mark_stale()

    def _revalidate(self) -> None:
        text = self._compute_validity()
        if text != self._validity:
            self._validity = text
            self.validityChanged.emit(text)

    def _compute_validity(self) -> str:
        if not self._rows:
            return EMPTY_ERROR
        errors = self.build_spec().validate()
        return errors[0] if errors else ""

    def _mark_stale(self) -> None:
        if self.result_path is not None and not self._stale:
            self._stale = True
            self.resultStale.emit()

    def _auto_names(self) -> dict[str, str]:
        faces = [r.face for r in self._rows]
        family = smart.default_family_name(faces)
        style = smart.default_style(self.main)
        return {"family": family, "style": style, "output": str(smart.default_output_path(family, style))}

    def _refresh_auto_names(self) -> None:
        auto = self._auto_names()
        changed = False
        for name in ("family", "style"):
            if not self._edited[name] and getattr(self, f"_{name}") != auto[name]:
                setattr(self, f"_{name}", auto[name])
                changed = True
        if not self._edited["output"]:
            output = str(smart.default_output_path(self._family, self._style))
            if output != self._output:
                self._output = output
                changed = True
        if changed:
            self.namesChanged.emit()

    def _set_name(self, name: str, text: str, by_user: bool) -> None:
        text_changed = getattr(self, f"_{name}") != text
        changed = text_changed
        if by_user and not self._edited[name]:
            self._edited[name] = True
            changed = True  # the flag itself is state the pages show ("prefilled" vs typed)
        setattr(self, f"_{name}", text)
        if name != "output" and not self._edited["output"]:
            output = str(smart.default_output_path(self._family, self._style))
            if output != self._output:
                self._output = output
                changed = True
        if not changed:
            return
        self.namesChanged.emit()
        if name == "output" or not text_changed:
            return  # where the file goes does not change what gets forged
        self._serial += 1
        self._revalidate()
        self._mark_stale()

    def _set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        self.busyChanged.emit(busy)

    def _on_progress(self, stage: str, fraction: float) -> None:
        self.progress.emit(stage_text(stage), fraction)

    def _on_succeeded(self, report) -> None:
        self.result_path = report.output_path
        self.result_report = report
        self._stale = False
        self._set_busy(False)
        self.resultReady.emit(report)
        if self._serial != self._serial_at_start:  # something changed while it ran
            self._mark_stale()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self.resultFailed.emit(message)

    def _on_cancelled(self) -> None:
        if self.worker is not None:  # the file may exist if the cancel landed between "finish" and "verify"
            try:
                Path(self.worker.output_path).unlink()
            except OSError:
                pass
        self._set_busy(False)
        self.resultCancelled.emit()
