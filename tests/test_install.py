import inspect
import shutil
import sys

import pytest

from fontplayground.ui import install
from fontplayground.ui.install import (FONTS_KEY, InstallNotSupported, full_name_of, install_font_for_user,
                                       installed_path, is_supported, registry_value_name, uninstall_font_for_user,
                                       user_fonts_dir)

windows_only = pytest.mark.skipif(not is_supported(), reason="per-user font install is Windows only")

TEST_FULL_NAME = "Font Playground Test Fixture A"


def test_module_does_not_need_qt():
    source = inspect.getsource(install)
    assert "PySide6" not in source and "QFontDatabase" not in source


def test_full_name_comes_from_the_name_table(font_dir):
    assert full_name_of(font_dir / "A.ttf") == "Fixture A"
    assert full_name_of(font_dir / "B.otf") == "Fixture B Bold"
    assert full_name_of(font_dir / "T.ttc") == "Fixture A & Fixture C"


def test_registry_value_name():
    assert registry_value_name("Fixture A") == "Fixture A (TrueType)"


def test_user_fonts_dir_follows_localappdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert user_fonts_dir() == tmp_path / "Microsoft" / "Windows" / "Fonts"


def test_copy_falls_back_to_numbered_name_when_locked(monkeypatch, font_dir, tmp_path):
    dest_dir = tmp_path / "fonts"
    real = shutil.copyfile
    locked = {dest_dir / "A.ttf", dest_dir / "A-1.ttf"}

    def copyfile(src, dst, *args, **kwargs):
        if dst in locked:
            raise PermissionError(13, "in use", str(dst))
        return real(src, dst, *args, **kwargs)
    monkeypatch.setattr(install.shutil, "copyfile", copyfile)

    assert install._copy_into(font_dir / "A.ttf", dest_dir) == dest_dir / "A-2.ttf"
    assert (dest_dir / "A-2.ttf").read_bytes() == (font_dir / "A.ttf").read_bytes()


def test_copy_overwrites_an_unlocked_earlier_copy(font_dir, tmp_path):
    dest_dir = tmp_path / "fonts"
    dest_dir.mkdir()
    (dest_dir / "A.ttf").write_bytes(b"old")
    assert install._copy_into(font_dir / "A.ttf", dest_dir) == dest_dir / "A.ttf"
    assert (dest_dir / "A.ttf").read_bytes() == (font_dir / "A.ttf").read_bytes()


def test_copy_from_the_font_folder_itself_is_a_no_op(font_dir, tmp_path):
    dest_dir = tmp_path / "fonts"
    dest_dir.mkdir()
    src = dest_dir / "A.ttf"
    shutil.copyfile(font_dir / "A.ttf", src)
    assert install._copy_into(src, dest_dir) == src


def test_not_supported_elsewhere(monkeypatch, font_dir):
    monkeypatch.setattr(sys, "platform", "linux")
    assert not is_supported()
    with pytest.raises(InstallNotSupported):
        install_font_for_user(font_dir / "A.ttf")
    with pytest.raises(InstallNotSupported):
        uninstall_font_for_user("Fixture A")
    with pytest.raises(InstallNotSupported):
        installed_path("Fixture A")


@windows_only
def test_install_and_uninstall_for_real(font_dir, tmp_path):
    import winreg

    src = tmp_path / "fontplayground-test-A.ttf"
    shutil.copyfile(font_dir / "A.ttf", src)
    value_name = registry_value_name(TEST_FULL_NAME)
    installed = None
    try:
        installed = install_font_for_user(src, TEST_FULL_NAME)
        assert installed == user_fonts_dir() / "fontplayground-test-A.ttf"
        assert installed.is_file() and installed.read_bytes() == src.read_bytes()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, FONTS_KEY) as key:
            value, kind = winreg.QueryValueEx(key, value_name)
        assert value == str(installed) and kind == winreg.REG_SZ
        assert installed_path(TEST_FULL_NAME) == installed
        # installing again (the file is not locked) overwrites in place and keeps the same registration
        assert install_font_for_user(src, TEST_FULL_NAME) == installed
    finally:
        removed = uninstall_font_for_user(TEST_FULL_NAME)
        if installed is not None and installed.exists():
            installed.unlink()
    assert removed is True
    assert installed is not None and not installed.exists()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, FONTS_KEY) as key:
        with pytest.raises(FileNotFoundError):
            winreg.QueryValueEx(key, value_name)
    assert installed_path(TEST_FULL_NAME) is None
    assert uninstall_font_for_user(TEST_FULL_NAME) is False


@windows_only
def test_install_reads_the_full_name_from_the_file(font_dir, tmp_path):
    if installed_path("Fixture A") is not None:
        pytest.skip("a font called 'Fixture A' is really installed for this user; not touching it")
    src = tmp_path / "fontplayground-test-named.ttf"
    shutil.copyfile(font_dir / "A.ttf", src)
    installed = None
    try:
        installed = install_font_for_user(src)
        assert installed_path("Fixture A") == installed
    finally:
        uninstall_font_for_user("Fixture A")
        if installed is not None and installed.exists():
            installed.unlink()
    assert installed_path("Fixture A") is None


@windows_only
def test_install_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        install_font_for_user(tmp_path / "nope.ttf", "Nope")
