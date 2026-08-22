import importlib
import subprocess

import pytest
from typer.testing import CliRunner

from gunkata.cli import shell
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


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


@pytest.fixture
def execvp_calls(monkeypatch):
    """Collect the argv `shell` would have replaced this process with."""
    calls: list[tuple] = []
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    return calls


def test_shell_command_execs_adb_rather_than_capturing_the_command(
    monkeypatch, execvp_calls
):
    """A regression guard: `gunkata shell <cmd>` must run <cmd> -- and must run
    it by replacing this process, never by capturing its output to echo once it
    exits. A captured command shows nothing until it finishes, so `top` and
    `logcat` show nothing at all."""
    fake = _ShellFakeAdb()
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["shell", "top"])
    assert result.exit_code == 0
    assert execvp_calls == [("adb", ["adb", "-s", "fake-serial", "shell", "top"])]
    assert fake.calls == []


def test_shell_command_requotes_a_token_the_invoking_shell_already_unquoted(
    monkeypatch, execvp_calls
):
    """`gunkata shell find . -name '*'` reaches this process with the glob
    already unquoted -- the invoking shell resolved that quoting itself,
    correctly, before argv ever got here. This command must re-quote it
    before handing it to the device, or the device's own shell parses a bare,
    unprotected glob instead of the literal character the caller guarded."""
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _ShellFakeAdb())
    result = CliRunner().invoke(app, ["shell", "find", ".", "-name", "*"])
    assert result.exit_code == 0
    assert execvp_calls[0][1][-1] == "find . -name '*'"


def test_shell_execs_into_an_interactive_shell_when_no_command_given(
    monkeypatch, execvp_calls
):
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _ShellFakeAdb())
    result = CliRunner().invoke(app, ["shell"])
    assert result.exit_code == 0
    assert execvp_calls[0][1][-1] == "exec sh"


def test_shell_command_honors_the_root_chdir_option(monkeypatch, execvp_calls):
    """`gunkata`'s root -C, not an option of `shell`'s own, supplies the
    chdir prefix: it must precede `shell` on the command line and reach this
    command through ctx.obj -- see app.py's root callback."""
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _ShellFakeAdb())
    result = CliRunner().invoke(app, ["-C", "/sdcard", "shell", "ls"])
    assert result.exit_code == 0
    assert execvp_calls[0][1][-1] == "cd /sdcard && ls"


def test_shell_attaches_in_the_root_chdir_option_when_no_command_is_given(
    monkeypatch, execvp_calls
):
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _ShellFakeAdb())
    result = CliRunner().invoke(app, ["-C", "/sdcard", "shell"])
    assert result.exit_code == 0
    assert execvp_calls[0][1][-1] == "cd /sdcard && exec sh"


@pytest.mark.parametrize(
    ("stdin", "stdout", "pty"),
    [(True, True, True), (True, False, False), (False, True, False)],
)
def test_shell_asks_for_a_pty_only_when_both_streams_are_terminals(
    monkeypatch, execvp_calls, stdin, stdout, pty
):
    """A pty is what gives `top` its window size, but it also merges stderr
    into stdout and translates newlines. adb's own -t consults stdin alone, so
    asking for one on stdin's word would corrupt `gunkata shell cat <binary>
    >file` run from a terminal."""
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _ShellFakeAdb())
    monkeypatch.setattr(shell, "stdin_is_tty", lambda: stdin)
    monkeypatch.setattr(shell, "stdout_is_tty", lambda: stdout)
    result = CliRunner().invoke(app, ["shell", "top"])
    assert result.exit_code == 0
    assert ("-t" in execvp_calls[0][1]) is pty
