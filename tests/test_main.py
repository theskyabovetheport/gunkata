import subprocess

import pytest
from typer.testing import CliRunner

from gunkata import main


@pytest.fixture(autouse=True)
def _isolated_completion_cache(tmp_path, monkeypatch):
    """Point the completion cache at a per-test file so tests never share state
    with each other or with the real cache used by actual shell completion."""
    monkeypatch.setattr(main, "_completion_cache_path", lambda: tmp_path / "cache.json")


class _FakeAdb:
    """Stands in for Adb: answers `command -v su` and `ls -1p` canned, counts real device calls.

    Returns bytes for stdout/stderr, matching real Adb (no text=True).
    """

    def __init__(self, ls_output: str, ls_ok: bool = True):
        self.serial = "fake-serial"
        self._ls_output = ls_output
        self._ls_ok = ls_ok
        self.su_check_calls = 0
        self.ls_calls = 0

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            self.su_check_calls += 1
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        self.ls_calls += 1
        returncode = 0 if self._ls_ok else 1
        return subprocess.CompletedProcess(
            args, returncode, self._ls_output.encode(), b""
        )


class _BrokenAdb:
    def __init__(self, *a, **k):
        raise RuntimeError("no adb device connected")


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
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["shell", "echo", "hello"])
    assert result.exit_code == 0
    assert "hello" in result.output


def test_shell_command_returns_the_remote_commands_exit_status(monkeypatch):
    fake = _ShellFakeAdb(stderr=b"nope\n", returncode=3)
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(main.app, ["shell", "false"])
    assert result.exit_code == 3


def test_shell_command_execs_into_an_interactive_shell_when_no_command_given(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _ShellFakeAdb())
    monkeypatch.setattr("os.execvp", lambda *args: calls.append(args))
    result = CliRunner().invoke(main.app, ["shell"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][0] == "adb"


def test_completes_nested_path(monkeypatch):
    monkeypatch.setattr(
        main, "Adb", lambda *a, **k: _FakeAdb("tmp/\nfoo.txt\n")
    )
    results = main._complete_remote_path(None, [], "/data/local/")
    assert results == ["/data/local/tmp/", "/data/local/foo.txt"]


def test_completes_root_path(monkeypatch):
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _FakeAdb("data/\nsdcard/\n"))
    results = main._complete_remote_path(None, [], "/")
    assert results == ["/data/", "/sdcard/"]


def test_completes_relative_path(monkeypatch):
    monkeypatch.setattr(main, "Adb", lambda *a, **k: _FakeAdb("a.txt\nb.txt\n"))
    results = main._complete_remote_path(None, [], "")
    assert results == ["a.txt", "b.txt"]


def test_returns_empty_on_ls_failure(monkeypatch):
    monkeypatch.setattr(
        main, "Adb", lambda *a, **k: _FakeAdb("", ls_ok=False)
    )
    assert main._complete_remote_path(None, [], "/no/such/dir") == []


def test_swallows_no_device_error(monkeypatch):
    """No device attached must never raise into the shell's completion prompt."""
    monkeypatch.setattr(main, "Adb", _BrokenAdb)
    assert main._complete_remote_path(None, [], "/data") == []


def test_second_call_for_same_dir_hits_cache_not_the_device(monkeypatch):
    """Retyping within the same directory must not re-run `command -v su` or `ls`."""
    fake = _FakeAdb("tmp/\n")
    monkeypatch.setattr(main, "Adb", lambda *a, **k: fake)
    first = main._complete_remote_path(None, [], "/data/local/t")
    second = main._complete_remote_path(None, [], "/data/local/tm")
    assert first == second == ["/data/local/tmp/"]
    assert fake.su_check_calls == 1
    assert fake.ls_calls == 1


@pytest.mark.emulator
def test_completes_against_real_device():
    """/data/local/tmp is a standard Android writable dir; must appear when completing its prefix."""
    results = main._complete_remote_path(None, [], "/data/local/tm")
    assert any(r.startswith("/data/local/tmp") for r in results)
