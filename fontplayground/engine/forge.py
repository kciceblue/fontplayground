"""Orchestrate a forge run: validate -> plan -> prepare -> merge -> finish -> verify."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from fontTools.ttLib import TTFont

from fontplayground.engine import merge as M
from fontplayground.engine.planner import plan
from fontplayground.engine.prepare import PreparedFont, prepare
from fontplayground.engine.scripts import groups_covered
from fontplayground.engine.spec import ForgeError, ForgeReport, ForgeSpec, MaterialReport, Plan

ProgressFn = Callable[[str, float], None]


def _report(spec: ForgeSpec, p: Plan, prepared: list[PreparedFont], n_cps: int, n_glyphs: int, out: str) -> ForgeReport:
    materials, warnings = [], []
    for i, (m, pf) in enumerate(zip(spec.materials, prepared)):
        notes = list(pf.warnings)
        if m.face.embedding == "restricted":
            notes.append("source licence forbids embedding (restricted); check before distributing")
        if not p.assignments[i]:
            notes.append("contributes no characters")
        materials.append(MaterialReport(m.face.display_name, len(p.assignments[i]), groups_covered(p.assignments[i]), notes))
        warnings += [f"{m.face.display_name}: {n}" for n in notes]
    return ForgeReport(materials, n_cps, n_glyphs, warnings, out)


def forge(spec: ForgeSpec, output_path: str | Path, progress: ProgressFn | None = None) -> ForgeReport:
    report_progress = progress or (lambda stage, fraction: None)
    errors = spec.validate()
    if errors:
        raise ForgeError("validate", None, " ".join(errors))
    report_progress("plan", 0.0)
    p = plan(spec)
    base = spec.materials[spec.base_index]
    out = Path(output_path)
    with tempfile.TemporaryDirectory(prefix="fontplayground-") as tmp:
        workdir = Path(tmp)
        prepared: list[PreparedFont] = []
        n = len(spec.materials)
        for i, m in enumerate(spec.materials):
            report_progress(f"prepare:{m.face.display_name}", 0.05 + 0.6 * i / n)
            try:
                prepared.append(prepare(m, p.assignments[i], base.face.upem, spec.resolved_weight(i),
                                        spec.resolved_scale(i), workdir, i))
            except ForgeError:
                raise
            except Exception as e:
                raise ForgeError("prepare", m.face.display_name, f"{type(e).__name__}: {e}") from e
        report_progress("merge", 0.7)
        try:
            font = M.merge_fonts([pf.path for pf in prepared])
        except Exception as e:
            raise ForgeError("merge", None, f"{type(e).__name__}: {e}") from e
        glyphs = len(font.getGlyphOrder())
        if glyphs > M.MAX_GLYPHS:
            raise ForgeError("merge", None, f"result has {glyphs} glyphs; TrueType allows {M.MAX_GLYPHS}. "
                                            "Assign fewer scripts or remove a material.")
        report_progress("finish", 0.85)
        base_font = TTFont(prepared[spec.base_index].path)
        try:
            weight = spec.resolved_weight(spec.base_index) or base.face.weight_class
            M.finish(font, spec, base_font, set(p.source), weight)
            out.parent.mkdir(parents=True, exist_ok=True)
            font.save(str(out))
        except ForgeError:
            raise
        except Exception as e:
            raise ForgeError("finish", None, f"{type(e).__name__}: {e}") from e
        finally:
            base_font.close()
            font.close()
    report_progress("verify", 0.95)
    n_cps, n_glyphs = M.verify(out, set(p.source))
    report = _report(spec, p, prepared, n_cps, n_glyphs, str(out))
    report_progress("done", 1.0)
    return report
