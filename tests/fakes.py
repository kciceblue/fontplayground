"""Stand-ins for the installer and the forge, shared by the build, action-bar and window tests."""
import shutil
import time
from pathlib import Path

from fontplayground.engine.spec import ForgeError, ForgeReport

NOTE = "Fixture B Bold: made bolder synthetically"


class FakeInstaller:
    """Records what would be installed or removed; never copies a file, never touches the registry."""

    def __init__(self, root: Path, supported: bool = True) -> None:
        self.supported = supported
        self.user_dir = root / "user"
        self.installs: list[tuple[str, str, bool]] = []     # (file name, full name, file existed)
        self.uninstalls: list[str] = []
        self.registered: dict[str, Path] = {}               # installed_path() answers
        self.forged: set[str] = set()                       # paths is_forged() says yes to
        self.uninstall_result = True
        self.install_error: Exception | None = None
        self.lookup_error: Exception | None = None

    def is_supported(self) -> bool:
        return self.supported

    def user_fonts_dir(self) -> Path:
        return self.user_dir

    def installed_path(self, full_name: str) -> Path | None:
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.registered.get(full_name)

    def is_forged(self, path) -> bool:
        return str(path) in self.forged

    def install_font_for_user(self, path, full_name=None) -> Path:
        if self.install_error is not None:
            raise self.install_error
        path = Path(path)
        self.installs.append((path.name, full_name, path.exists()))
        return self.user_dir / path.name

    def uninstall_font_for_user(self, full_name: str) -> bool:
        self.uninstalls.append(full_name)
        return self.uninstall_result


def copying_forge(font_dir: Path, calls: list, warnings=(NOTE,)):
    """A quick forge(): reports three stages and copies fixture A to the output (a real font file)."""
    def forge(spec, output_path, progress=None):
        calls.append(output_path)
        progress("plan", 0.2)
        progress("merge", 0.5)
        shutil.copyfile(font_dir / "A.ttf", output_path)
        progress("done", 1.0)
        return ForgeReport([], 5, 6, list(warnings), str(output_path))
    return forge


def waiting_forge(spec, output_path, progress=None):
    """A forge() that keeps reporting progress until the worker cancels it (or 10 s pass)."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        progress("waiting", 0.0)  # raises ForgeError('cancelled') once cancel() has been called
        time.sleep(0.01)
    raise ForgeError("test", None, "never cancelled")
