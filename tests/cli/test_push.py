import importlib
import subprocess

from typer.testing import CliRunner

from gunkata.cli import push  # noqa: F401 -- imported for its command registration
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


class _PushFakeAdb:
    """Records commands and reads back the fd passed as stdin=, like real adb streams a push.

    Reports `[ -d <path> ]` success only for the paths in `dirs`, so a test can
    say whether the push target is a directory on the device.
    """

    _DIR_TEST_PREFIX = "[ -d "
    _DIR_TEST_SUFFIX = " ]"

    def __init__(self, dirs: tuple[str, ...] = ()):
        self.serial = "fake-serial"
        self.commands: list[str] = []
        self.pushed = b""
        self._dirs = dirs

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1]
        self.commands.append(command)
        stdin = kwargs.get("stdin")
        if stdin is not None and stdin is not subprocess.DEVNULL:
            self.pushed = stdin.read()
        return subprocess.CompletedProcess(args, self._returncode(command), b"", b"")

    def _returncode(self, command: str) -> int:
        if not (
            command.startswith(self._DIR_TEST_PREFIX)
            and command.endswith(self._DIR_TEST_SUFFIX)
        ):
            return 0
        probed = command[len(self._DIR_TEST_PREFIX) : -len(self._DIR_TEST_SUFFIX)]
        return 0 if probed in self._dirs else 1


def test_push_writes_the_device_path_it_was_given(monkeypatch, tmp_path):
    adb = _PushFakeAdb()
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: adb)
    lpath = tmp_path / "src.bin"
    lpath.write_bytes(b"payload")
    result = CliRunner().invoke(app, ["push", str(lpath), "/data/local/tmp/dst.bin"])
    assert result.exit_code == 0
    assert "cat >/data/local/tmp/dst.bin" in adb.commands
    assert adb.pushed == b"payload"


def test_push_appends_the_local_basename_to_a_device_directory(monkeypatch, tmp_path):
    """`gk push ./src.bin /data/local/tmp` must land /data/local/tmp/src.bin,
    not fail on a redirect into a directory."""
    adb = _PushFakeAdb(dirs=("/data/local/tmp",))
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: adb)
    lpath = tmp_path / "src.bin"
    lpath.write_bytes(b"payload")
    result = CliRunner().invoke(app, ["push", str(lpath), "/data/local/tmp"])
    assert result.exit_code == 0
    assert "cat >/data/local/tmp/src.bin" in adb.commands
    assert adb.pushed == b"payload"
