import shutil

import pytest

from fontplayground.catalog import scanner
from fontplayground.catalog.cache import CatalogCache, face_from_dict, face_to_dict
from fontplayground.catalog.face import read_faces


def test_face_dict_roundtrip(font_dir):
    (v,) = read_faces(font_dir / "V.ttf")
    d = face_to_dict(v)
    assert d["codepoints"] == [[97, 98]] and d["axes"] == [["wght", 100.0, 400.0, 900.0]]
    assert face_from_dict(d) == v


def test_find_font_files(font_dir, tmp_path):
    (tmp_path / "sub").mkdir()
    shutil.copy(font_dir / "A.ttf", tmp_path / "sub" / "A.ttf")
    (tmp_path / "junk.fon").write_bytes(b"x")
    assert [p.name for p in scanner.find_font_files([tmp_path])] == ["A.ttf"]


def test_scan_reports_faces_failures_and_progress(font_dir, tmp_path):
    shutil.copytree(font_dir, tmp_path / "f")
    (tmp_path / "f" / "broken.ttf").write_bytes(b"not a font")
    seen, progress = [], []
    result = scanner.scan([tmp_path / "f"], on_face=seen.append, on_progress=lambda d, t: progress.append((d, t)))
    assert len(result.faces) == 6 and len(seen) == 6  # A, B, C, V, T(2 faces)
    assert [p for p, _ in result.failed] == [str(tmp_path / "f" / "broken.ttf")]
    assert progress[-1] == (6, 6)


def test_scan_uses_cache_until_file_changes(font_dir, tmp_path, monkeypatch):
    shutil.copy(font_dir / "A.ttf", tmp_path / "A.ttf")
    cache = CatalogCache(tmp_path / "cache.json")
    first = scanner.scan([tmp_path], cache=cache)
    assert (tmp_path / "cache.json").exists()

    cache2 = CatalogCache(tmp_path / "cache.json"); cache2.load()
    monkeypatch.setattr(scanner, "read_faces", lambda p: pytest.fail("should have used cache"))
    second = scanner.scan([tmp_path], cache=cache2)
    assert second.faces == first.faces

    monkeypatch.undo()
    (tmp_path / "A.ttf").touch()
    import os, time
    os.utime(tmp_path / "A.ttf", (time.time() + 100, time.time() + 100))
    calls = []
    real = read_faces
    monkeypatch.setattr(scanner, "read_faces", lambda p: calls.append(p) or real(p))
    scanner.scan([tmp_path], cache=cache2)
    assert calls, "changed mtime must force a re-read"
