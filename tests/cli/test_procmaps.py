import subprocess

from typer.testing import CliRunner

from gunkata.cli import fzf, procmaps
from gunkata.cli.app import app


class _ProcmapsFakeAdb:
    """Answers `command -v su`, `pidof <name>`, `ps -A`, and `cat /proc/<pid>/maps` canned."""

    def __init__(
        self,
        pidof_output: str = "",
        maps: bytes = b"",
        maps_ok: bool = True,
        ps_output: str = "",
    ):
        self.serial = "fake-serial"
        self._pidof_output = pidof_output
        self._maps = maps
        self._maps_ok = maps_ok
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
        if "cat /proc" in command:
            if self._maps_ok:
                return subprocess.CompletedProcess(args, 0, self._maps, b"")
            return subprocess.CompletedProcess(
                args, 1, b"", b"No such file or directory\n"
            )
        raise AssertionError(f"unexpected command: {command!r}")


def test_procmaps_prints_maps_for_given_pid(monkeypatch):
    fake = _ProcmapsFakeAdb(maps=b"7f0000-7f1000 r-xp 0 00:00 0 /lib/libc.so\n")
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["procmaps", "-p", "1234"])
    assert result.exit_code == 0
    assert "libc.so" in result.output


def test_procmaps_resolves_pid_by_name(monkeypatch):
    """`-P name` must resolve to the sole matching pid before reading its maps."""
    fake = _ProcmapsFakeAdb(pidof_output="1234\n", maps=b"deadbeef\n")
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["procmaps", "-P", "com.example.app"])
    assert result.exit_code == 0
    assert "deadbeef" in result.output


def test_procmaps_rejects_both_p_and_capital_p():
    result = CliRunner().invoke(
        app, ["procmaps", "-p", "1234", "-P", "com.example.app"]
    )
    assert result.exit_code == 2


def test_procmaps_errors_when_name_matches_multiple_processes(monkeypatch):
    """Wiring guard: ProcMaps.AmbiguousProcessError must map to CLI exit 1, not propagate."""
    fake = _ProcmapsFakeAdb(pidof_output="1234 5678\n")
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["procmaps", "-P", "com.example.app"])
    assert result.exit_code == 1


def test_procmaps_errors_when_pid_has_no_proc_entry(monkeypatch):
    fake = _ProcmapsFakeAdb(maps_ok=False)
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["procmaps", "-p", "9999"])
    assert result.exit_code == 1


def test_procmaps_with_no_flags_launches_fzf_and_reads_the_picked_pid(monkeypatch):
    fake = _ProcmapsFakeAdb(
        maps=b"deadbeef\n",
        ps_output="USER  PID  PPID S NAME\nu0_a1 1234 567  S com.example.app\n",
    )
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(procmaps, "stdout_is_tty", lambda: True)
    monkeypatch.setattr(fzf.shutil, "which", lambda name: "/usr/bin/fzf")
    monkeypatch.setattr(
        fzf.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "1234\tcom.example.app\n", ""),
    )
    result = CliRunner().invoke(app, ["procmaps"])
    assert result.exit_code == 0
    assert "deadbeef" in result.output


def test_procmaps_with_no_flags_exits_when_fzf_is_missing(monkeypatch):
    fake = _ProcmapsFakeAdb()
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(procmaps, "stdout_is_tty", lambda: True)
    monkeypatch.setattr(fzf.shutil, "which", lambda name: None)
    result = CliRunner().invoke(app, ["procmaps"])
    assert result.exit_code == 1
    assert "fzf" in result.output


def test_procmaps_with_no_flags_refuses_to_fuzzy_pick_when_stdout_is_not_a_tty(
    monkeypatch,
):
    """Piped/redirected stdout must never trigger fzf; -p/-P are the only way in."""
    fake = _ProcmapsFakeAdb()
    monkeypatch.setattr(procmaps, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(procmaps, "stdout_is_tty", lambda: False)
    result = CliRunner().invoke(app, ["procmaps"])
    assert result.exit_code == 2
    assert "tty" in result.output
