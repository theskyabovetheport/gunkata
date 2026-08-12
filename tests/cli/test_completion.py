import subprocess

import pytest

from gunkata.cli import completion


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


def test_completes_nested_path(monkeypatch):
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: _FakeAdb("tmp/\nfoo.txt\n"))
    results = completion.complete_remote_path(None, [], "/data/local/")
    assert results == ["/data/local/tmp/", "/data/local/foo.txt"]


def test_completes_root_path(monkeypatch):
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: _FakeAdb("data/\nsdcard/\n"))
    results = completion.complete_remote_path(None, [], "/")
    assert results == ["/data/", "/sdcard/"]


def test_completes_relative_path(monkeypatch):
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: _FakeAdb("a.txt\nb.txt\n"))
    results = completion.complete_remote_path(None, [], "")
    assert results == ["a.txt", "b.txt"]


def test_returns_empty_on_ls_failure(monkeypatch):
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: _FakeAdb("", ls_ok=False))
    assert completion.complete_remote_path(None, [], "/no/such/dir") == []


def test_swallows_no_device_error(monkeypatch):
    """No device attached must never raise into the shell's completion prompt."""
    monkeypatch.setattr(completion, "Adb", _BrokenAdb)
    assert completion.complete_remote_path(None, [], "/data") == []


def test_second_call_for_same_dir_hits_cache_not_the_device(monkeypatch):
    """Retyping within the same directory must not re-run `command -v su` or `ls`."""
    fake = _FakeAdb("tmp/\n")
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: fake)
    first = completion.complete_remote_path(None, [], "/data/local/t")
    second = completion.complete_remote_path(None, [], "/data/local/tm")
    assert first == second == ["/data/local/tmp/"]
    assert fake.su_check_calls == 1
    assert fake.ls_calls == 1


class _PsFakeAdb:
    """Answers `command -v su` and `ps -A` canned; counts real `ps -A` calls."""

    def __init__(self, ps_output: str):
        self.serial = "fake-serial"
        self._ps_output = ps_output
        self.ps_calls = 0

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        self.ps_calls += 1
        return subprocess.CompletedProcess(args, 0, self._ps_output.encode(), b"")


_PS_OUTPUT = (
    "USER  PID  PPID VSZ RSS WCHAN ADDR S NAME\n"
    "u0_a1 1234 567  1   1   0     0    S com.example.app\n"
    "u0_a2 5678 567  1   1   0     0    S com.example.other\n"
)


def test_completes_process_name(monkeypatch):
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: _PsFakeAdb(_PS_OUTPUT))
    assert completion.complete_process_name(None, [], "com.example.a") == [
        "com.example.app"
    ]


def test_process_name_completion_hits_cache_not_the_device(monkeypatch):
    """Retyping within the TTL must not re-run `ps -A`, matching the path completer's caching."""
    fake = _PsFakeAdb(_PS_OUTPUT)
    monkeypatch.setattr(completion, "Adb", lambda *a, **k: fake)
    first = completion.complete_process_name(None, [], "com.example.a")
    second = completion.complete_process_name(None, [], "com.example.o")
    assert first == ["com.example.app"]
    assert second == ["com.example.other"]
    assert fake.ps_calls == 1


@pytest.mark.emulator
def test_completes_against_real_device():
    """/data/local/tmp is a standard Android writable dir; must appear when completing its prefix."""
    results = completion.complete_remote_path(None, [], "/data/local/tm")
    assert any(r.startswith("/data/local/tmp") for r in results)
