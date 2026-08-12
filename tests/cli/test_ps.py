import subprocess

from gunkata.cli import ps


class _PsFakeAdb:
    """Answers `command -v su` and `ps -A` canned."""

    def __init__(self, ps_output: str):
        self.serial = "fake-serial"
        self._ps_output = ps_output

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        return subprocess.CompletedProcess(args, 0, self._ps_output.encode(), b"")


_PS_OUTPUT = (
    "USER  PID  PPID VSZ RSS WCHAN ADDR S NAME\n"
    "u0_a1 1234 567  1   1   0     0    S com.example.app\n"
    "u0_a2 5678 567  1   1   0     0    S com.example.other\n"
)


def test_ps_prints_aligned_columns_with_a_header_on_a_tty(monkeypatch, capsys):
    """A terminal reader gets a table; column width follows the widest pid, not a fixed guess."""
    monkeypatch.setattr(ps, "Adb", lambda *a, **k: _PsFakeAdb(_PS_OUTPUT))
    monkeypatch.setattr(ps, "stdout_is_tty", lambda: True)
    ps.ps()
    assert capsys.readouterr().out.splitlines() == [
        "PID   NAME",
        "1234  com.example.app",
        "5678  com.example.other",
    ]


def test_ps_prints_unaligned_pid_and_name_when_piped(monkeypatch, capsys):
    """A pipeline gets one space between pid and name -- no header, no column padding."""
    monkeypatch.setattr(ps, "Adb", lambda *a, **k: _PsFakeAdb(_PS_OUTPUT))
    monkeypatch.setattr(ps, "stdout_is_tty", lambda: False)
    ps.ps()
    assert capsys.readouterr().out.splitlines() == [
        "1234 com.example.app",
        "5678 com.example.other",
    ]
