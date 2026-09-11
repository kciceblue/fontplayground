"""Walk font directories and read every face, with optional cache."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from fontplayground.catalog.cache import CatalogCache
from fontplayground.catalog.face import FontFace, read_faces
from fontplayground.paths import is_font_file


@dataclass
class ScanResult:
    faces: list[FontFace] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (path, error)


def find_font_files(dirs: Iterable[Path]) -> list[Path]:
    seen: dict[str, Path] = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.is_file() and is_font_file(p):
                seen.setdefault(str(p.resolve()).lower(), p)
    return sorted(seen.values(), key=lambda p: str(p).lower())


def scan(dirs: Iterable[Path], cache: CatalogCache | None = None, on_face: Callable[[FontFace], None] | None = None,
         on_progress: Callable[[int, int], None] | None = None, use_cache: bool = True,
         should_stop: Callable[[], bool] | None = None) -> ScanResult:
    files = find_font_files(dirs)
    result = ScanResult()
    for i, path in enumerate(files):
        if should_stop and should_stop():
            break
        try:
            st = path.stat()
            faces = cache.get(str(path), st.st_size, st.st_mtime) if (cache and use_cache) else None
            if faces is None:
                faces = read_faces(path)
                if cache:
                    cache.put(str(path), st.st_size, st.st_mtime, faces)
        except Exception as e:  # unreadable or corrupt file
            result.failed.append((str(path), f"{type(e).__name__}: {e}"))
            faces = []
        for f in faces:
            result.faces.append(f)
            if on_face:
                on_face(f)
        if on_progress:
            on_progress(i + 1, len(files))
    if cache:
        cache.save()
    return result
