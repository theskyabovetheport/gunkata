import subprocess

from typer.testing import CliRunner

from gunkata.cli import shell
from gunkata.cli.app import app


class _ShellFakeAdb:
    """Answers `command -v su` canned; any other command returns a fixed result."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        return subprocess.CompletedProcess(
            args, self._returncode, self._stdout, self._stderr
        )


def test_shell_command_runs_a_one_shot_command_and_exits_with_its_rc(monkeypatch):
    """A regression guard: `gunkata shell <cmd>` must run <cmd> and exit, not attach interactively."""
    fake = _ShellFakeAdb(stdout=b"hello\n", returncode=0)
    monkeypatch.setattr(shell, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["shell", "echo", "hello"])
    assert result.exit_code == 0
    assert "hello" in result.output


def test_shell_command_returns_the_remote_commands_exit_status(monkeypatch):
    fake = _ShellFakeAdb(stderr=b"nope\n", returncode=3)
    monkeypatch.setattr(shell, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["shell", "false"])
    assert result.exit_code == 3


def test_shell_command_execs_into_an_interactive_shell_when_no_command_given(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(shell, "Adb", lambda *a, **k: _ShellFakeAdb())
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    result = CliRunner().invoke(app, ["shell"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "adb"
