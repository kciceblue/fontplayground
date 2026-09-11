"""JSON cache of FontFace metadata keyed by file path, size and mtime."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fontplayground.catalog.face import FontFace


def _ranges(codepoints) -> list[list[int]]:
    out: list[list[int]] = []
    for cp in sorted(codepoints):
        if out and cp == out[-1][1] + 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return out


def _expand(ranges) -> frozenset[int]:
    return frozenset(cp for lo, hi in ranges for cp in range(lo, hi + 1))


def face_to_dict(face: FontFace) -> dict:
    d = asdict(face)
    d["codepoints"] = _ranges(face.codepoints)
    d["axes"] = [list(a) for a in face.axes]
    return d


def face_from_dict(d: dict) -> FontFace:
    d = dict(d)
    d["codepoints"] = _expand(d["codepoints"])
    d["axes"] = tuple(tuple(a) for a in d["axes"])
    return FontFace(**d)


class CatalogCache:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: dict[str, dict] = {}

    def load(self) -> None:
        try:
            self._entries = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._entries = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries), encoding="utf-8")

    def get(self, path: str, size: int, mtime: float) -> list[FontFace] | None:
        e = self._entries.get(path)
        if not e or e["size"] != size or abs(e["mtime"] - mtime) > 1e-6:
            return None
        return [face_from_dict(f) for f in e["faces"]]

    def put(self, path: str, size: int, mtime: float, faces: list[FontFace]) -> None:
        self._entries[path] = {"size": size, "mtime": mtime, "faces": [face_to_dict(f) for f in faces]}
