import pytest

from gunkata.procmaps import AmbiguousProcessError, NoSuchProcessError, ProcMaps


class _FakeShell:
    """Stands in for Shell: answers pidof/read_file canned, records what it read."""

    def __init__(self, pids: list[int] | None = None, maps: bytes = b""):
        self._pids = pids if pids is not None else []
        self._maps = maps
        self.read_paths: list[str] = []

    def pidof(self, name: str) -> list[int]:
        return self._pids

    def read_file(self, dpath: str) -> bytes:
        self.read_paths.append(dpath)
        if dpath not in {f"/proc/{pid}/maps" for pid in self._pids} and self._pids:
            raise FileNotFoundError(dpath)
        return self._maps


def test_by_pid_reads_the_pids_maps_file():
    shell = _FakeShell(maps=b"7f0000-7f1000 r-xp 0 00:00 0 /lib/libc.so\n")
    assert ProcMaps(shell).by_pid(1234) == b"7f0000-7f1000 r-xp 0 00:00 0 /lib/libc.so\n"
    assert shell.read_paths == ["/proc/1234/maps"]


def test_by_pid_raises_no_such_process_when_proc_entry_is_missing():
    class _MissingShell:
        def read_file(self, dpath: str) -> bytes:
            raise FileNotFoundError(dpath)

    with pytest.raises(NoSuchProcessError):
        ProcMaps(_MissingShell()).by_pid(9999)


def test_by_name_resolves_the_sole_pid_and_reads_its_maps():
    shell = _FakeShell(pids=[1234], maps=b"deadbeef\n")
    assert ProcMaps(shell).by_name("com.example.app") == b"deadbeef\n"
    assert shell.read_paths == ["/proc/1234/maps"]


def test_by_name_raises_no_such_process_when_nothing_matches():
    with pytest.raises(NoSuchProcessError):
        ProcMaps(_FakeShell(pids=[])).by_name("no.such.app")


def test_by_name_raises_ambiguous_process_when_multiple_pids_match():
    """More than one process sharing a name must not silently pick one."""
    with pytest.raises(AmbiguousProcessError) as exc_info:
        ProcMaps(_FakeShell(pids=[1234, 5678])).by_name("com.example.app")
    assert exc_info.value.pids == [1234, 5678]
