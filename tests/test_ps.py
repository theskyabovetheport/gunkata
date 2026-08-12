import pytest

from gunkata.ps import ProcessEntry, Ps
from gunkata.types import ShellError, ShellResult

# A real toybox `ps -A` header and a couple of rows, columns aligned as the
# device pads them.
_TOYBOX = """\
USER           PID  PPID     VSZ    RSS WCHAN              ADDR S NAME
root             1     0 1234567  12345 SyS_epoll_wait          0 S init
u0_a123       1234   567 2345678  23456 futex_wait_queue_me     0 S com.example.app
u0_a123       1235   567 2345678  23456 futex_wait_queue_me     0 S com.example.app
"""


class _FakeShell:
    """Stands in for Shell: answers `ps -A` canned, counts real device calls."""

    def __init__(self, stdout: str = "", ok: bool = True):
        self._stdout = stdout
        self._ok = ok
        self.calls = 0

    def check_sh(self, command: str) -> ShellResult:
        self.calls += 1
        if not self._ok:
            raise ShellError(command, "permission denied", 1)
        return ShellResult(command=command, stdout=self._stdout, stderr="", rc=0)


def test_entries_parses_pid_and_name_by_column_position():
    entries = Ps(_FakeShell(_TOYBOX)).entries()
    assert entries == [
        ProcessEntry(pid=1, name="init"),
        ProcessEntry(pid=1234, name="com.example.app"),
        ProcessEntry(pid=1235, name="com.example.app"),
    ]


def test_entries_caches_after_the_first_call():
    """A second entries() call must not re-run `ps -A`; see Ps's Design note."""
    shell = _FakeShell(_TOYBOX)
    ps = Ps(shell)
    assert ps.entries() == ps.entries()
    assert shell.calls == 1


def test_refresh_re_queries_the_device():
    shell = _FakeShell(_TOYBOX)
    ps = Ps(shell)
    ps.entries()
    ps.refresh()
    assert shell.calls == 2


def test_names_collapses_duplicate_names_in_first_seen_order():
    names = Ps(_FakeShell(_TOYBOX)).names()
    assert names == ["init", "com.example.app"]


def test_entries_propagates_shell_error():
    with pytest.raises(ShellError):
        Ps(_FakeShell(ok=False)).entries()
