import json
import shutil

import pytest

from fontplayground.catalog import cache as cache_module
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
    assert len(result.faces) == 7 and len(seen) == 7  # A, B, C, K, V, T(2 faces)
    assert [p for p, _ in result.failed] == [str(tmp_path / "f" / "broken.ttf")]
    assert progress[-1] == (7, 7)


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


def _scan_once_into_cache(font_dir, tmp_path) -> tuple:
    shutil.copy(font_dir / "A.ttf", tmp_path / "A.ttf")
    cache = CatalogCache(tmp_path / "cache.json")
    faces = scanner.scan([tmp_path], cache=cache).faces
    data = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    return faces, data


def test_cache_file_carries_schema_and_rejects_other_versions(font_dir, tmp_path, monkeypatch):
    faces, data = _scan_once_into_cache(font_dir, tmp_path)
    assert data["schema"] == cache_module.SCHEMA
    assert set(data["entries"]) == {str(tmp_path / "A.ttf")}
    st = (tmp_path / "A.ttf").stat()

    fresh = CatalogCache(tmp_path / "cache.json"); fresh.load()
    assert fresh.get(str(tmp_path / "A.ttf"), st.st_size, st.st_mtime) == faces

    # a file written by another schema version is discarded as a whole
    data["schema"] = cache_module.SCHEMA + 1
    (tmp_path / "cache.json").write_text(json.dumps(data), encoding="utf-8")
    other = CatalogCache(tmp_path / "cache.json"); other.load()
    assert other.get(str(tmp_path / "A.ttf"), st.st_size, st.st_mtime) is None
    # ...and so is the old schema-less layout (a bare dict of entries)
    (tmp_path / "cache.json").write_text(json.dumps(data["entries"]), encoding="utf-8")
    legacy = CatalogCache(tmp_path / "cache.json"); legacy.load()
    assert legacy.get(str(tmp_path / "A.ttf"), st.st_size, st.st_mtime) is None
    # a discarded cache does not make the scanner report the file as unreadable
    calls = []
    real = read_faces
    monkeypatch.setattr(scanner, "read_faces", lambda p: calls.append(p) or real(p))
    result = scanner.scan([tmp_path], cache=legacy)
    assert result.faces == faces and not result.failed and calls == [tmp_path / "A.ttf"]


def test_cache_drops_entries_it_cannot_rebuild_and_rereads_the_file(font_dir, tmp_path, monkeypatch):
    faces, data = _scan_once_into_cache(font_dir, tmp_path)
    key = str(tmp_path / "A.ttf")
    st = (tmp_path / "A.ttf").stat()

    # a face dict from before a FontFace field was added (or after one was renamed) cannot be rebuilt
    del data["entries"][key]["faces"][0]["upem"]
    (tmp_path / "cache.json").write_text(json.dumps(data), encoding="utf-8")
    cache = CatalogCache(tmp_path / "cache.json"); cache.load()
    assert cache.get(key, st.st_size, st.st_mtime) is None
    cache.save()
    assert json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))["entries"] == {}

    # an entry that is not even the right shape is dropped the same way
    data["entries"][key] = {"size": st.st_size, "mtime": st.st_mtime, "faces": ["not a dict"]}
    (tmp_path / "cache.json").write_text(json.dumps(data), encoding="utf-8")
    cache = CatalogCache(tmp_path / "cache.json"); cache.load()
    assert cache.get(key, st.st_size, st.st_mtime) is None
    data["entries"][key] = {"faces": []}  # no size/mtime at all
    (tmp_path / "cache.json").write_text(json.dumps(data), encoding="utf-8")
    cache = CatalogCache(tmp_path / "cache.json"); cache.load()
    assert cache.get(key, st.st_size, st.st_mtime) is None

    # the scanner re-reads the file instead of counting it as unreadable, and the cache is repaired
    data["entries"][key] = {"size": st.st_size, "mtime": st.st_mtime, "faces": [{"path": key}]}
    (tmp_path / "cache.json").write_text(json.dumps(data), encoding="utf-8")
    cache = CatalogCache(tmp_path / "cache.json"); cache.load()
    calls = []
    real = read_faces
    monkeypatch.setattr(scanner, "read_faces", lambda p: calls.append(p) or real(p))
    result = scanner.scan([tmp_path], cache=cache)
    assert result.faces == faces and not result.failed and calls == [tmp_path / "A.ttf"]
    repaired = CatalogCache(tmp_path / "cache.json"); repaired.load()
    assert repaired.get(key, st.st_size, st.st_mtime) == faces
