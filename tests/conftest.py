import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.fixtures import build_collection, build_font, cps  # noqa: E402


@pytest.fixture(scope="session")
def font_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("fonts")
    a = build_font(d / "A.ttf", "Fixture A", "Regular", cps("abc1,"))
    build_font(d / "B.otf", "Fixture B", "Bold", cps("ab漢，"), cff=True, weight=700)
    c = build_font(d / "C.ttf", "Fixture C", "Regular", cps("a→Ω"), upem=2048, fs_type=2)
    build_font(d / "V.ttf", "Fixture V", "Regular", cps("ab"), variable=True)
    build_collection(d / "T.ttc", [a, c])
    return d
