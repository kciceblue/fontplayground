import json

from PySide6.QtCore import Qt

from fontplayground.catalog.face import read_faces
from fontplayground.ui.app import MainWindow


def _open(qtbot, font_dir, cfg):
    w = MainWindow([font_dir], cfg)
    qtbot.addWidget(w)
    with qtbot.waitSignal(w.scan_worker.finished_scan, timeout=30000):
        pass
    return w


def _face_item(w, face):
    tree = w.fonts_tab.tree
    for i in range(tree.topLevelItemCount()):
        fam = tree.topLevelItem(i)
        for j in range(fam.childCount()):
            child = fam.child(j)
            if child.data(0, Qt.ItemDataRole.UserRole) == face.key:
                return child
    raise AssertionError(f"no row for {face.key}")


def test_scan_populates_fonts_and_cache(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    assert len(w.fonts_tab.faces_by_key()) == 6
    assert (tmp_path / "cfg" / "catalog.json").exists()


def test_ticking_feeds_forge_and_persists(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    (a,) = read_faces(font_dir / "A.ttf")
    _face_item(w, a).setCheckState(0, Qt.CheckState.Checked)
    assert len(w.forge_tab.rows()) == 1
    saved = json.loads((tmp_path / "cfg" / "forge_last.json").read_text(encoding="utf-8"))
    assert len(saved["materials"]) == 1 and saved["materials"][0]["path"] == a.path


def test_forge_settings_are_restored(qtbot, font_dir, tmp_path):
    (a,) = read_faces(font_dir / "A.ttf")
    (b,) = read_faces(font_dir / "B.otf")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "forge_last.json").write_text(json.dumps({
        "materials": [{"path": b.path, "index": 0, "weight": 500, "scale": None},
                      {"path": a.path, "index": 0, "weight": None, "scale": None}],
        "base_index": 1, "script_rules": {"han": 0}, "default_weight": None, "default_scale": 1.0,
        "family_name": "Restored", "style_name": "Regular", "output_path": str(tmp_path / "r.ttf"),
    }), encoding="utf-8")
    w = _open(qtbot, font_dir, cfg)
    spec = w.forge_tab.build_spec()
    assert [m.face.key for m in spec.materials] == [b.key, a.key]
    assert spec.materials[0].weight == 500 and spec.base_index == 1
    assert spec.script_rules["han"] == 0 and spec.family_name == "Restored"
    assert w.fonts_tab.selected_faces() and {f.key for f in w.fonts_tab.selected_faces()} == {a.key, b.key}


def test_sample_text_is_shared_between_tabs(qtbot, font_dir, tmp_path):
    w = _open(qtbot, font_dir, tmp_path / "cfg")
    w.fonts_preview.editor.setPlainText("shared sample")
    assert w.forge_preview.sample_text() == "shared sample"
    w.forge_preview.editor.setPlainText("back again")
    assert w.fonts_preview.sample_text() == "back again"
