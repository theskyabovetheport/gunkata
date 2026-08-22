"""A device process's memory map: fetched from /proc/<pid>/maps, parsed on demand."""

import re
from dataclasses import dataclass

from .shell import Shell


class NoSuchProcessError(RuntimeError):
    """Neither a pid nor a name resolved to a live process on the device."""

    def __init__(self, target: str):
        self.target = target
        super().__init__(f"no such process: {target}")


class AmbiguousProcessError(RuntimeError):
    """A name matched more than one pid; the caller must pick one.

    Attributes:
        name: The name that was looked up.
        pids: Every pid that matched, in the order the device reported them.
    """

    def __init__(self, name: str, pids: list[int]):
        self.name = name
        self.pids = pids
        super().__init__(f"multiple processes named {name!r}: {pids}")


@dataclass
class MemoryMapping:
    """One line of a /proc/<pid>/maps listing, split into its fields.

    Attributes:
        line: The line exactly as it was read, trailing whitespace stripped.
        start: Start address of the mapping.
        end: End address of the mapping, exclusive.
        perms: Permission flags, e.g. "r-xp".
        offset: Offset into the mapped file.
        dev: Device the mapped file lives on, as "<major>:<minor>".
        inode: Inode of the mapped file, 0 for anonymous mappings.
        pathname: The mapped file's path, or "" for anonymous mappings.
    """

    line: str
    start: int
    end: int
    perms: str
    offset: int
    dev: str
    inode: int
    pathname: str


class ProcMaps:
    """A /proc/<pid>/maps listing: fetched from a device, or parsed from raw bytes.

    Args:
        maps: The listing, exactly as /proc/<pid>/maps or `gunkata procmaps`
            produced it.

    Design:
        Parsing is deferred to the first call to mappings()/find()/index_of(),
        not done in __init__: a caller that only wants .raw -- `gunkata
        procmaps`'s stdout dump, piped on to `gunkata addr` -- must be able to
        fetch and forward a listing byte-for-byte even if some future kernel's
        maps line this parser doesn't understand slips in. by_pid/by_name
        never raise ValueError; only asking for the parsed mappings can.

        Parsing works over bytes, not a decoded string: every fixed field
        (hex addresses, "r-xp", "08:01", digits) is ASCII, so only the
        trailing pathname -- and the stored per-mapping `line` -- ever needs
        .decode(errors="replace"). .raw itself is never decoded, so it is
        always the exact bytes the device (or caller) produced.
    """

    _LINE = re.compile(
        rb"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+([0-9a-f]+)\s+(\S+)\s+(\d+)\s*(.*)$"
    )

    def __init__(self, maps: bytes):
        self._raw = maps
        self._mappings: list[MemoryMapping] | None = None

    @property
    def raw(self) -> bytes:
        """The listing this instance was built from, exactly as read."""
        return self._raw

    def mappings(self) -> list[MemoryMapping]:
        """Every mapping, in the order /proc/<pid>/maps listed them.

        Raises:
            ValueError: A non-blank line doesn't match /proc/<pid>/maps' format.
        """
        return list(self._parsed())

    def find(self, address: int) -> MemoryMapping | None:
        """The mapping containing address.

        Returns:
            The mapping whose [start, end) range contains address, or None
            if address falls in a gap or outside every mapping.

        Raises:
            ValueError: A non-blank line doesn't match /proc/<pid>/maps' format.
        """
        for mapping in self._parsed():
            if mapping.start <= address < mapping.end:
                return mapping
        return None

    def index_of(self, mapping: MemoryMapping) -> int:
        """mapping's position among mappings(), in listing order.

        Raises:
            ValueError: mapping is not one of this listing's mappings.
        """
        return self._parsed().index(mapping)

    @classmethod
    def by_pid(cls, shell: Shell, pid: int) -> "ProcMaps":
        """Read /proc/<pid>/maps.

        Raises:
            NoSuchProcessError: pid has no /proc entry.
        """
        try:
            return cls(shell.read_file(f"/proc/{pid}/maps"))
        except FileNotFoundError:
            raise NoSuchProcessError(str(pid)) from None

    @classmethod
    def by_name(cls, shell: Shell, name: str) -> "ProcMaps":
        """Resolve name to its sole pid, then read that pid's maps.

        Raises:
            NoSuchProcessError: name matched no running process.
            AmbiguousProcessError: name matched more than one running process.
        """
        pids = shell.pidof(name)
        if not pids:
            raise NoSuchProcessError(name)
        if len(pids) > 1:
            raise AmbiguousProcessError(name, pids)
        return cls.by_pid(shell, pids[0])

    def _parsed(self) -> list[MemoryMapping]:
        if self._mappings is None:
            self._mappings = [
                self._parse_line(line)
                for line in self._raw.splitlines()
                if line.strip()
            ]
        return self._mappings

    @classmethod
    def _parse_line(cls, line: bytes) -> MemoryMapping:
        match = cls._LINE.match(line.strip())
        if match is None:
            raise ValueError(f"not a /proc/<pid>/maps line: {line!r}")
        return MemoryMapping(
            line=line.rstrip().decode("utf-8", errors="replace"),
            start=int(match[1], 16),
            end=int(match[2], 16),
            perms=match[3].decode("utf-8", errors="replace"),
            offset=int(match[4], 16),
            dev=match[5].decode("utf-8", errors="replace"),
            inode=int(match[6]),
            pathname=match[7].strip().decode("utf-8", errors="replace"),
        )
