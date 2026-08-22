import importlib
import subprocess

from typer.testing import CliRunner

from gunkata.cli import fzf, pidof
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


class _PidofFakeAdb:
    """Answers `command -v su`, `pidof <name>`, and `ps -A` canned."""

    def __init__(self, pidof_output: str = "", ps_output: str = ""):
        self.serial = "fake-serial"
        self._pidof_output = pidof_output
        self._ps_output = ps_output

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        if "pidof" in command:
            return subprocess.CompletedProcess(
                args, 0, self._pidof_output.encode(), b""
            )
        if "ps -A" in command:
            return subprocess.CompletedProcess(args, 0, self._ps_output.encode(), b"")
        raise AssertionError(f"unexpected command: {command!r}")


def test_pidof_prints_every_pid_matching_the_given_name(monkeypatch):
    fake = _PidofFakeAdb(pidof_output="1234 5678\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["pidof", "com.example.app"])
    assert result.exit_code == 0
    assert result.output.splitlines() == ["1234", "5678"]


def test_pidof_errors_when_name_matches_no_process(monkeypatch):
    fake = _PidofFakeAdb(pidof_output="")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["pidof", "no.such.app"])
    assert result.exit_code == 1


def test_pidof_launches_fzf_and_prints_the_picked_pid(monkeypatch):
    fake = _PidofFakeAdb(
        ps_output="USER  PID  PPID S NAME\nu0_a1 1234 567  S com.example.app\n",
    )
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(fzf.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        fzf.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "1234\tcom.example.app\n", ""),
    )
    result = CliRunner().invoke(app, ["pidof"])
    assert result.exit_code == 0
    assert result.output.strip() == "1234"


def test_pidof_exits_when_fzf_is_missing(monkeypatch):
    fake = _PidofFakeAdb()
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(fzf.shutil, "which", lambda name: None)
    result = CliRunner().invoke(app, ["pidof"])
    assert result.exit_code == 1
    assert "fzf" in result.output
