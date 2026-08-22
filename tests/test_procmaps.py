import pytest

from gunkata.procmaps import (
    AmbiguousProcessError,
    MemoryMapping,
    NoSuchProcessError,
    ProcMaps,
)


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
    assert ProcMaps.by_pid(shell, 1234).raw == b"7f0000-7f1000 r-xp 0 00:00 0 /lib/libc.so\n"
    assert shell.read_paths == ["/proc/1234/maps"]


def test_by_pid_raises_no_such_process_when_proc_entry_is_missing():
    class _MissingShell:
        def read_file(self, dpath: str) -> bytes:
            raise FileNotFoundError(dpath)

    with pytest.raises(NoSuchProcessError):
        ProcMaps.by_pid(_MissingShell(), 9999)


def test_by_name_resolves_the_sole_pid_and_reads_its_maps():
    shell = _FakeShell(pids=[1234], maps=b"deadbeef\n")
    assert ProcMaps.by_name(shell, "com.example.app").raw == b"deadbeef\n"
    assert shell.read_paths == ["/proc/1234/maps"]


def test_by_name_raises_no_such_process_when_nothing_matches():
    with pytest.raises(NoSuchProcessError):
        ProcMaps.by_name(_FakeShell(pids=[]), "no.such.app")


def test_by_name_raises_ambiguous_process_when_multiple_pids_match():
    """More than one process sharing a name must not silently pick one."""
    with pytest.raises(AmbiguousProcessError) as exc_info:
        ProcMaps.by_name(_FakeShell(pids=[1234, 5678]), "com.example.app")
    assert exc_info.value.pids == [1234, 5678]


def test_by_pid_does_not_parse_eagerly():
    """Fetching must succeed even for a listing this parser can't understand --
    raw dumping (`gunkata procmaps`) must not depend on parseability."""
    shell = _FakeShell(maps=b"not a maps line\n")
    assert ProcMaps.by_pid(shell, 1234).raw == b"not a maps line\n"


_MAPS = (
    b"7f0000-7f1000 r-xp 00001000 08:01 131099 /lib/libc.so\n"
    b"7f2000-7f3000 rw-p 00000000 00:00 0 [anon]\n"
    b"7f4000-7f5000 r--p 00000000 00:00 0\n"
)


def test_mappings_parses_every_field_of_a_line_with_a_pathname():
    mapping = ProcMaps(_MAPS).mappings()[0]
    assert mapping == MemoryMapping(
        line="7f0000-7f1000 r-xp 00001000 08:01 131099 /lib/libc.so",
        start=0x7F0000,
        end=0x7F1000,
        perms="r-xp",
        offset=0x1000,
        dev="08:01",
        inode=131099,
        pathname="/lib/libc.so",
    )


def test_mappings_defaults_pathname_to_empty_when_a_line_has_none():
    mapping = ProcMaps(_MAPS).mappings()[2]
    assert mapping.pathname == ""


def test_mappings_preserves_listing_order():
    procmaps = ProcMaps(_MAPS)
    assert [m.start for m in procmaps.mappings()] == [0x7F0000, 0x7F2000, 0x7F4000]


def test_mappings_skips_blank_lines():
    assert ProcMaps(b"\n" + _MAPS + b"\n").mappings() == ProcMaps(_MAPS).mappings()


def test_mappings_rejects_a_line_that_does_not_match_the_maps_format():
    with pytest.raises(ValueError):
        ProcMaps(b"not a maps line\n").mappings()


def test_raw_is_available_even_when_the_listing_does_not_parse():
    """.raw never depends on a successful parse -- see ProcMaps' Design note."""
    procmaps = ProcMaps(b"not a maps line\n")
    assert procmaps.raw == b"not a maps line\n"


def test_find_returns_the_mapping_containing_address():
    procmaps = ProcMaps(_MAPS)
    assert procmaps.find(0x7F0010).pathname == "/lib/libc.so"


def test_find_returns_none_for_an_address_in_a_gap():
    assert ProcMaps(_MAPS).find(0x7F1800) is None


def test_find_returns_none_for_an_address_past_every_mapping():
    assert ProcMaps(_MAPS).find(0x800000) is None


def test_index_of_returns_the_mappings_position_in_listing_order():
    procmaps = ProcMaps(_MAPS)
    mappings = procmaps.mappings()
    assert procmaps.index_of(mappings[2]) == 2


def test_index_of_raises_for_a_mapping_not_from_this_listing():
    procmaps = ProcMaps(_MAPS)
    foreign = ProcMaps(b"1000-2000 r--p 00000000 00:00 0 x\n").mappings()[0]
    with pytest.raises(ValueError):
        procmaps.index_of(foreign)
