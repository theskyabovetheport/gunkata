import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from gunkata.frida.server import FridaServer, FridaServerError
from gunkata.settings import SuBinary
from gunkata.shell import Shell
from gunkata.types import ShellResult


class _FakeRepo:
    """Yields a throwaway local binary path, and counts how often it is asked."""

    def __init__(self, tmp_path: Path):
        self._path = tmp_path / "frida-server"
        self._path.write_bytes(b"ELF")
        self.extract_calls = 0

    @contextmanager
    def extracted(self, shell, version=None):
        self.extract_calls += 1
        yield self._path


class _FakeStream:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeShell:
    """A programmable Shell double for FridaServer.

    pidof answers come from a FIFO so a test can script a sequence like
    "not running, then running, then gone" across a start/stop run; an empty
    queue answers "not running".
    """

    def __init__(self, pidof_answers, file_exists=True):
        self._pidof = list(pidof_answers)
        self._file_exists = file_exists
        self.commands: list[str] = []
        self.pushed: list[tuple[str, str, bool]] = []
        self.chmods: list[tuple[str, str]] = []
        self.streams: list[_FakeStream] = []

    def pidof(self, name: str) -> list[int]:
        return self._pidof.pop(0) if self._pidof else []

    def file_exists(self, dpath: str) -> bool:
        return self._file_exists

    def push_file(self, dpath, lpath, inherit_owner=True):
        self.pushed.append((dpath, lpath, inherit_owner))

    def chmod(self, dpath, mode):
        self.chmods.append((dpath, mode))

    def check_sh(self, command, strip=True):
        self.commands.append(command)
        return ShellResult(command=command, stdout="", stderr="", rc=0)

    def stream(self, command):
        self.commands.append(command)
        stream = _FakeStream()
        self.streams.append(stream)
        return stream


def _server(shell, tmp_path, **kw):
    return FridaServer(shell, _FakeRepo(tmp_path), **kw)


def test_install_pushes_then_marks_executable(tmp_path):
    shell = _FakeShell(pidof_answers=[], file_exists=False)
    server = _server(shell, tmp_path)
    assert server.install() == FridaServer.DEFAULT_DEVICE_PATH
    assert shell.pushed == [
        (FridaServer.DEFAULT_DEVICE_PATH, str(tmp_path / "frida-server"), False)
    ]
    assert shell.chmods == [(FridaServer.DEFAULT_DEVICE_PATH, "755")]


def test_start_launches_detached_and_returns_the_awaited_pids(tmp_path, monkeypatch):
    monkeypatch.setattr(FridaServer, "_POLL_INTERVAL_SECONDS", 0.0)
    shell = _FakeShell(pidof_answers=[[], [4242]], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.start() == [4242]
    assert any("-D -l 127.0.0.1:27042" in c for c in shell.commands)


def test_start_is_idempotent_when_already_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[99]], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.start() == [99]
    assert shell.commands == []
    assert shell.pushed == []


def test_start_times_out_naming_path_and_port(tmp_path, monkeypatch):
    monkeypatch.setattr(FridaServer, "_START_TIMEOUT_SECONDS", 0.0)
    monkeypatch.setattr(FridaServer, "_POLL_INTERVAL_SECONDS", 0.0)
    shell = _FakeShell(pidof_answers=[[]], file_exists=True)
    server = _server(shell, tmp_path, port=1234)
    with pytest.raises(FridaServerError) as exc:
        server.start()
    assert "1234" in str(exc.value)
    assert FridaServer.DEFAULT_DEVICE_PATH in str(exc.value)


def test_stop_kills_the_reported_pids(tmp_path, monkeypatch):
    monkeypatch.setattr(FridaServer, "_STOP_GRACE_SECONDS", 0.0)
    shell = _FakeShell(pidof_answers=[[7], []], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.stop() == [7]
    assert shell.commands == ["kill 7"]


def test_stop_escalates_to_sigkill_when_a_pid_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(FridaServer, "_STOP_GRACE_SECONDS", 0.0)
    shell = _FakeShell(pidof_answers=[[7], [7], []], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.stop() == [7]
    assert shell.commands == ["kill 7", "kill -9 7"]


def test_stop_is_a_noop_when_nothing_is_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[]], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.stop() == []
    assert shell.commands == []


def test_scoped_run_streams_the_foreground_command_and_reaps(tmp_path, monkeypatch):
    monkeypatch.setattr(FridaServer, "_POLL_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(FridaServer, "_STOP_GRACE_SECONDS", 0.0)
    shell = _FakeShell(pidof_answers=[[], [55], []], file_exists=True)
    server = _server(shell, tmp_path)
    with server.running() as running:
        assert running is server
    foreground = [c for c in shell.commands if c.endswith("-l 127.0.0.1:27042")]
    assert foreground and all("-D" not in c for c in foreground)
    assert shell.streams[0].closed


def test_scoped_run_refuses_when_a_server_is_already_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[1]], file_exists=True)
    server = _server(shell, tmp_path)
    with pytest.raises(FridaServerError):
        with server.running():
            pass


def test_constructor_refuses_an_unsafe_device_path(tmp_path):
    with pytest.raises(ValueError):
        FridaServer(_FakeShell([]), _FakeRepo(tmp_path), device_path="/tmp/x; rm -rf /")


def test_constructor_refuses_an_out_of_range_port(tmp_path):
    with pytest.raises(ValueError):
        FridaServer(_FakeShell([]), _FakeRepo(tmp_path), port=70000)


class _SpyAdb:
    """Runs no process; answers pidof empty until a ``-D`` launch is seen, then
    reports a pid, so a real Shell can drive one full start()."""

    def __init__(self):
        self.serial = "fake"
        self.calls: list[list[str]] = []
        self._launched = False

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        command = args[-1] if args and args[0] == "shell" else ""
        if "-D -l" in command:
            self._launched = True
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if "pidof" in command:
            out = b"4242\n" if self._launched else b""
            return subprocess.CompletedProcess(args, 0, out, b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


def test_start_reaches_the_device_wrapped_in_su(tmp_path, monkeypatch):
    """The detached launch must reach adb through the same su wrapping every other
    command uses -- delivery must not smuggle a differently-wrapped command."""
    monkeypatch.setattr(FridaServer, "_POLL_INTERVAL_SECONDS", 0.0)
    adb = _SpyAdb()
    shell = Shell(adb, user="root", su=SuBinary.for_device("su"))
    FridaServer(shell, _FakeRepo(tmp_path)).start()
    assert [
        "shell",
        "su root sh -c '/data/local/tmp/frida-server -D -l 127.0.0.1:27042 "
        "</dev/null >/dev/null 2>&1'",
    ] in adb.calls
