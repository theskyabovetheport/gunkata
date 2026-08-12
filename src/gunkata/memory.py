"""A device process's memory, read and written through /proc/<pid>/mem."""

import re

from .procmaps import ProcMaps
from .shell import Shell


class UnmappedRangeError(RuntimeError):
    """A byte range isn't fully covered by any region a process currently has mapped.

    Attributes:
        pid: Process the range was checked against.
        start: First byte's address, inclusive.
        end: Address one past the last byte, exclusive.
    """

    def __init__(self, pid: int, start: int, end: int):
        self.pid = pid
        self.start = start
        self.end = end
        super().__init__(f"0x{start:x}-0x{end:x} is not fully mapped in pid {pid}")


class Memory:
    """One process's memory, read and written through /proc/<pid>/mem.

    Args:
        shell: Shell the underlying dd commands run under; its user decides
            which processes' memory is accessible.
        pid: Process whose memory this operates on.

    Design:
        Every read and write is checked against a freshly-read
        /proc/<pid>/maps first: a stale check would let a range that was
        mapped a moment ago silently read or write into memory that no
        longer belongs to this process.

        Seeking is done with ``dd bs=1``, not a larger block size with a
        byte-offset flag: that flag (``iflag=skip_bytes`` / ``oflag=seek_bytes``)
        is a GNU dd extension toybox and busybox don't both carry, and a
        block size this tool cannot assume would silently misalign every
        read and write. The cost is one syscall per byte, traded for
        working the same on every dd this device might ship.
    """

    _MAP_LINE = re.compile(rb"^([0-9a-f]+)-([0-9a-f]+)\s")

    def __init__(self, shell: Shell, pid: int):
        self._shell = shell
        self._pid = pid
        self._procmaps = ProcMaps(shell)

    def read(self, start: int, end: int) -> bytes:
        """Read the byte range [start, end) from this process's memory.

        Args:
            start: First byte's address, inclusive.
            end: Address one past the last byte read, exclusive.

        Returns:
            Exactly end - start bytes.

        Raises:
            ValueError: end is not greater than start.
            UnmappedRangeError: [start, end) isn't fully covered by this
                process's currently mapped regions.
            NoSuchProcessError: pid has no /proc entry.
        """
        self._check_range(start, end)
        command = f"dd if=/proc/{self._pid}/mem bs=1 skip={start} count={end - start}"
        return self._shell.read_bytes(command)

    def write(self, start: int, data: bytes, end: int | None = None) -> None:
        """Write data into this process's memory starting at start.

        Args:
            start: First byte's address, inclusive.
            end: An upper bound the write must not cross, checked against
                start + len(data) before anything is written. None skips
                this check; the mapped-range check below still applies.

        Raises:
            ValueError: end is given and start + len(data) exceeds it.
            UnmappedRangeError: [start, start + len(data)) isn't fully
                covered by this process's currently mapped regions.
            NoSuchProcessError: pid has no /proc entry.
        """
        write_end = start + len(data)
        if end is not None and write_end > end:
            raise ValueError(
                f"writing {len(data)} bytes at 0x{start:x} would reach "
                f"0x{write_end:x}, past the given end 0x{end:x}"
            )
        self._check_range(start, write_end)
        command = f"dd of=/proc/{self._pid}/mem bs=1 seek={start} conv=notrunc"
        self._shell.write_bytes(command, data)

    def _check_range(self, start: int, end: int) -> None:
        if end <= start:
            raise ValueError(
                f"end (0x{end:x}) must be greater than start (0x{start:x})"
            )
        if not self._is_mapped(start, end):
            raise UnmappedRangeError(self._pid, start, end)

    def _is_mapped(self, start: int, end: int) -> bool:
        """Whether every byte in [start, end) falls within some mapped region."""
        pos = start
        for region_start, region_end in self._regions():
            if region_end <= pos:
                continue
            if region_start > pos:
                return False
            pos = max(pos, region_end)
            if pos >= end:
                return True
        return pos >= end

    def _regions(self) -> list[tuple[int, int]]:
        """This process's mapped regions, as [start, end) pairs sorted by start."""
        raw = self._procmaps.by_pid(self._pid)
        regions = [
            (int(match[1], 16), int(match[2], 16))
            for line in raw.splitlines()
            if (match := self._MAP_LINE.match(line))
        ]
        return sorted(regions)
