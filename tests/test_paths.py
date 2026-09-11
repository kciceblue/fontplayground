from pathlib import Path

from fontplayground import paths


def test_windows_dirs():
    env = {"WINDIR": r"C:\Win", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
    dirs = paths.default_font_dirs("win32", env, Path("C:/Users/u"))
    assert dirs == [Path(r"C:\Win\Fonts"), Path(r"C:\Users\u\AppData\Local\Microsoft\Windows\Fonts")]


def test_mac_and_linux_dirs():
    home = Path("/home/u")
    assert Path("/Library/Fonts") in paths.default_font_dirs("darwin", {}, home)
    assert home / ".local" / "share" / "fonts" in paths.default_font_dirs("linux", {}, home)


def test_config_dir():
    assert paths.config_dir("win32", {"LOCALAPPDATA": r"C:\L"}, Path("C:/u")) == Path(r"C:\L\FontPlayground")
    assert paths.config_dir("darwin", {}, Path("/h")) == Path("/h/Library/Application Support/FontPlayground")
    assert paths.config_dir("linux", {}, Path("/h")) == Path("/h/.config/fontplayground")


def test_is_font_file():
    assert paths.is_font_file(Path("x.TTF")) and paths.is_font_file(Path("x.otc"))
    assert not paths.is_font_file(Path("x.fon"))
