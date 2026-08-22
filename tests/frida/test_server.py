import importlib.util
import subprocess
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from gunkata.frida import server as server_mod
from gunkata.frida.server import FridaNotReadyError, FridaServer, FridaServerError
from gunkata.frida.settings import FridaSettings
from gunkata.shell import Shell, ShellResult
from gunkata.su import Su

_NO_WAIT = FridaSettings(
    start_timeout_seconds=0.0, stop_grace_seconds=0.0, poll_interval_seconds=0.0
)


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
        self.serial = "emulator-5554"
        self._pidof = list(pidof_answers)
        self._file_exists = file_exists
        self.commands: list[str] = []
        self.pushed: list[tuple[str, str, bool]] = []
        self.chmods: list[tuple[str, str]] = []
        self.streams: list[_FakeStream] = []
        self.pidof_calls = 0

    def pidof(self, name: str) -> list[int]:
        self.pidof_calls += 1
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
    default_path = FridaSettings().device_path
    assert server.install() == default_path
    assert shell.pushed == [(default_path, str(tmp_path / "frida-server"), False)]
    assert shell.chmods == [(default_path, "755")]


class _ReachedRepo(Exception):
    """Raised by _MarkerRepo to prove which repo provisioning actually reads."""


class _MarkerRepo:
    """A ServerRepo double that only reports having been asked for a binary."""

    def extracted(self, shell, version=None):
        raise _ReachedRepo


def test_constructor_defaults_its_repo_to_the_configured_factory(monkeypatch):
    """A caller with no opinion about where archives live provisions out of the
    process's configured repo, resolved by calling server_repo() once."""
    calls = []

    def _spy():
        calls.append(True)
        return _MarkerRepo()

    monkeypatch.setattr(server_mod, "server_repo", _spy)
    server = FridaServer(_FakeShell([]))
    with pytest.raises(_ReachedRepo):
        server.install()
    assert len(calls) == 1


def test_constructor_keeps_the_repo_it_was_given(monkeypatch):
    """An explicit repo is the one provisioning reads, and the factory is never
    consulted -- so a caller can point provisioning at its own directory."""

    def _unreachable():
        raise AssertionError("server_repo() consulted despite an explicit repo")

    monkeypatch.setattr(server_mod, "server_repo", _unreachable)
    server = FridaServer(_FakeShell([]), _MarkerRepo())
    with pytest.raises(_ReachedRepo):
        server.install()


def test_start_launches_detached_and_returns_the_awaited_pids(tmp_path):
    shell = _FakeShell(pidof_answers=[[], [4242]], file_exists=True)
    server = _server(shell, tmp_path, settings=_NO_WAIT)
    assert server.start() == [4242]
    assert any("-D -l 127.0.0.1:27042" in c for c in shell.commands)


def test_start_is_idempotent_when_already_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[99]], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.start() == [99]
    assert shell.commands == []
    assert shell.pushed == []


def test_start_times_out_naming_path_and_port(tmp_path):
    shell = _FakeShell(pidof_answers=[[]], file_exists=True)
    server = _server(shell, tmp_path, port=1234, settings=_NO_WAIT)
    with pytest.raises(FridaServerError) as exc:
        server.start()
    assert "1234" in str(exc.value)
    assert FridaSettings().device_path in str(exc.value)


def test_stop_kills_the_reported_pids(tmp_path):
    shell = _FakeShell(pidof_answers=[[7], []], file_exists=True)
    server = _server(shell, tmp_path, settings=_NO_WAIT)
    assert server.stop() == [7]
    assert shell.commands == ["kill 7"]


def test_stop_escalates_to_sigkill_when_a_pid_survives(tmp_path):
    shell = _FakeShell(pidof_answers=[[7], [7], []], file_exists=True)
    server = _server(shell, tmp_path, settings=_NO_WAIT)
    assert server.stop() == [7]
    assert shell.commands == ["kill 7", "kill -9 7"]


def test_stop_is_a_noop_when_nothing_is_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[]], file_exists=True)
    server = _server(shell, tmp_path)
    assert server.stop() == []
    assert shell.commands == []


def test_scoped_run_streams_the_foreground_command_and_reaps(tmp_path):
    shell = _FakeShell(pidof_answers=[[], [55], []], file_exists=True)
    server = _server(shell, tmp_path, settings=_NO_WAIT)
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


def test_is_running_reports_true_without_a_device_round_trip_when_assumed(tmp_path):
    """assume_running answers is_running() from the assumption alone -- the
    fake's pidof would say "not running" if consulted, proving it never is."""
    shell = _FakeShell(pidof_answers=[[]], file_exists=True)
    server = _server(shell, tmp_path, assume_running=True)
    assert server.is_running() is True
    assert shell.pidof_calls == 0


def test_start_is_a_noop_when_assume_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[123]], file_exists=True)
    server = _server(shell, tmp_path, assume_running=True)
    assert server.start() == []
    assert shell.pidof_calls == 0
    assert shell.commands == []
    assert shell.pushed == []


def test_stop_refuses_when_assume_running(tmp_path):
    shell = _FakeShell(pidof_answers=[[123]], file_exists=True)
    server = _server(shell, tmp_path, assume_running=True)
    with pytest.raises(FridaServerError):
        server.stop()
    assert shell.pidof_calls == 0
    assert shell.commands == []


def test_scoped_run_is_a_noop_when_assume_running(tmp_path):
    """running() under assume_running never launches or reaps anything -- it
    just yields this server, since this instance owns no lifecycle to scope."""
    shell = _FakeShell(pidof_answers=[[123]], file_exists=True)
    server = _server(shell, tmp_path, assume_running=True)
    with server.running() as running:
        assert running is server
    assert shell.pidof_calls == 0
    assert shell.streams == []
    assert shell.commands == []


def test_constructor_defaults_assume_running_from_settings(tmp_path):
    settings = FridaSettings(assume_running=True)
    shell = _FakeShell(pidof_answers=[[]], file_exists=True)
    server = _server(shell, tmp_path, settings=settings)
    assert server.is_running() is True


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


class _FakeFridaError(Exception):
    pass


class _FakeFridaDevice:
    """A fake frida device whose server answers only after ``fails`` refusals."""

    def __init__(self, fails: int):
        self._fails = fails
        self.queries = 0

    def query_system_parameters(self):
        self.queries += 1
        if self.queries <= self._fails:
            raise _FakeFridaError("not ready")
        return {"os": {"version": "14"}}


def _fake_frida(device):
    manager = types.SimpleNamespace(get_device=lambda serial, timeout: device)
    return types.SimpleNamespace(Error=_FakeFridaError, get_device_manager=lambda: manager)


def test_get_device_retries_until_the_server_answers(tmp_path, monkeypatch):
    device = _FakeFridaDevice(fails=2)
    monkeypatch.setattr(server_mod, "import_frida", lambda: _fake_frida(device))
    server = _server(_FakeShell([]), tmp_path)
    got = server.get_device(timeout=5.0, poll=0.0)
    assert got is device
    assert device.queries == 3


def test_get_device_times_out_naming_the_serial(tmp_path, monkeypatch):
    device = _FakeFridaDevice(fails=10**9)
    monkeypatch.setattr(server_mod, "import_frida", lambda: _fake_frida(device))
    server = _server(_FakeShell([]), tmp_path)
    with pytest.raises(FridaNotReadyError) as exc:
        server.get_device(timeout=0.0, poll=0.0)
    assert "emulator-5554" in str(exc.value)


@pytest.mark.emulator
@pytest.mark.skipif(
    importlib.util.find_spec("frida") is None, reason="frida extra not installed"
)
def test_get_device_against_real_device(device):
    """With frida-server running, get_device binds to the serial and the
    server answers a system-parameters query."""
    server = FridaServer(device.shell())
    server.start()
    try:
        got = server.get_device()
        assert "os" in got.query_system_parameters()
    finally:
        server.stop()


def test_start_reaches_the_device_wrapped_in_su(tmp_path):
    """The detached launch must reach adb through the same su wrapping every other
    command uses -- delivery must not smuggle a differently-wrapped command."""
    adb = _SpyAdb()
    shell = Shell(adb, user="root", su=Su())
    FridaServer(shell, _FakeRepo(tmp_path), settings=_NO_WAIT).start()
    assert [
        "shell",
        "su root sh -c '/data/local/tmp/frida-server -D -l 127.0.0.1:27042 "
        "</dev/null >/dev/null 2>&1'",
    ] in adb.calls
