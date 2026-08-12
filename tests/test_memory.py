import pytest

from gunkata.memory import Memory, UnmappedRangeError
from gunkata.procmaps import ProcMaps
from gunkata.types import ShellError


class _FakeShell:
    """Stands in for Shell: answers read_file(maps)/read_bytes/write_bytes canned."""

    def __init__(self, maps: bytes = b"", read_result: bytes = b"", ok: bool = True):
        self._maps = maps
        self._read_result = read_result
        self._ok = ok
        self.read_commands: list[str] = []
        self.write_calls: list[tuple[str, bytes]] = []

    def read_file(self, dpath: str) -> bytes:
        return self._maps

    def read_bytes(self, command: str) -> bytes:
        self.read_commands.append(command)
        if not self._ok:
            raise ShellError(command, "", 1)
        return self._read_result

    def write_bytes(self, command: str, data: bytes) -> None:
        self.write_calls.append((command, data))
        if not self._ok:
            raise ShellError(command, "", 1)


# Two mapped regions, [0x7f0000000000, 0x7f0000010000) and
# [0x7f0000020000, 0x7f0000030000), with a gap between them -- real
# /proc/<pid>/maps addresses are hex without a "0x" prefix.
_MAPS = (
    b"7f0000000000-7f0000010000 r-xp 00000000 00:00 0 /lib/libc.so\n"
    b"7f0000020000-7f0000030000 rw-p 00000000 00:00 0\n"
)


def _memory(**shell_kwargs) -> Memory:
    shell = _FakeShell(**shell_kwargs)
    return Memory(shell, pid=1234, procmaps=ProcMaps(shell))


def test_read_returns_bytes_for_a_fully_mapped_range():
    shell = _FakeShell(maps=_MAPS, read_result=b"payload")
    memory = Memory(shell, pid=1234, procmaps=ProcMaps(shell))
    assert memory.read(0x7F0000000000, 0x7F0000000007) == b"payload"
    assert shell.read_commands == [
        f"dd if=/proc/1234/mem bs=1 skip={0x7F0000000000} count=7"
    ]


def test_read_raises_value_error_when_end_is_not_after_start():
    memory = _memory(maps=_MAPS)
    with pytest.raises(ValueError):
        memory.read(0x7F0000000010, 0x7F0000000010)


def test_read_raises_unmapped_range_error_when_start_is_outside_every_region():
    memory = _memory(maps=_MAPS)
    with pytest.raises(UnmappedRangeError):
        memory.read(0x1, 0x10)


def test_read_raises_unmapped_range_error_when_the_range_crosses_a_gap():
    """The range starts inside a mapped region but extends past its end into
    the gap before the next region -- must fail, not silently truncate."""
    memory = _memory(maps=_MAPS)
    with pytest.raises(UnmappedRangeError):
        memory.read(0x7F0000005000, 0x7F0000025000)


def test_read_propagates_shell_error_from_the_underlying_dd():
    memory = _memory(maps=_MAPS, ok=False)
    with pytest.raises(ShellError):
        memory.read(0x7F0000000000, 0x7F0000000010)


def test_write_sends_data_to_a_fully_mapped_range():
    shell = _FakeShell(maps=_MAPS)
    memory = Memory(shell, pid=1234, procmaps=ProcMaps(shell))
    memory.write(0x7F0000000000, b"hi")
    assert shell.write_calls == [
        (f"dd of=/proc/1234/mem bs=1 seek={0x7F0000000000} conv=notrunc", b"hi")
    ]


def test_write_raises_unmapped_range_error_when_data_would_cross_a_gap():
    memory = _memory(maps=_MAPS)
    with pytest.raises(UnmappedRangeError):
        memory.write(0x7F000000FFF0, b"x" * 20)


def test_write_raises_unmapped_range_error_when_start_is_outside_every_region():
    memory = _memory(maps=_MAPS)
    with pytest.raises(UnmappedRangeError):
        memory.write(0x1, b"x")


def test_write_raises_value_error_when_data_would_exceed_the_given_end():
    memory = _memory(maps=_MAPS)
    with pytest.raises(ValueError):
        memory.write(0x7F0000000000, b"0123456789", end=0x7F0000000005)


def test_write_within_the_given_end_succeeds():
    shell = _FakeShell(maps=_MAPS)
    memory = Memory(shell, pid=1234, procmaps=ProcMaps(shell))
    memory.write(0x7F0000000000, b"hi", end=0x7F0000000010)
    assert shell.write_calls == [
        (f"dd of=/proc/1234/mem bs=1 seek={0x7F0000000000} conv=notrunc", b"hi")
    ]


@pytest.mark.emulator
def test_read_write_round_trip_against_real_device(device):
    """The one thing a fake shell can't prove: that dd's bs=1 skip=/seek=
    arithmetic actually addresses the byte gunkata means it to, on a real su
    and a real toybox dd."""
    shell = device.shell()
    # Redirected, not just backgrounded: an inherited stdout pipe kept open by
    # the child would block capture_output's read until sleep itself exits.
    pid = int(shell.check_sh("sleep 300 >/dev/null 2>&1 & echo $!").stdout)
    try:
        maps = device.procmaps().by_pid(pid).decode("utf-8", errors="replace")
        region = next(line for line in maps.splitlines() if " rw-p " in line)
        start = int(region.split("-")[0], 16)

        memory = device.memory(pid)
        payload = b"gunkata memory round trip\n"
        memory.write(start, payload)
        assert memory.read(start, start + len(payload)) == payload
    finally:
        shell(f"kill {pid}")
