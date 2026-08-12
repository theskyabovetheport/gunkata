"""Parses a /proc/<pid>/maps listing into structured mappings."""

import re
from dataclasses import dataclass


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


class ProcMapsParser:
    """Parses a /proc/<pid>/maps listing into a list of MemoryMapping.

    Args:
        procmaps_data: The listing, exactly as /proc/<pid>/maps or `gunkata
            procmaps` produced it.

    Raises:
        ValueError: A non-blank line doesn't match /proc/<pid>/maps' format.
    """

    _LINE = re.compile(
        r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+([0-9a-f]+)\s+(\S+)\s+(\d+)\s*(.*)$"
    )

    def __init__(self, procmaps_data: str):
        self._mappings = [
            self._parse_line(line)
            for line in procmaps_data.splitlines()
            if line.strip()
        ]

    def mappings(self) -> list[MemoryMapping]:
        """Every mapping, in the order /proc/<pid>/maps listed them."""
        return list(self._mappings)

    def find(self, address: int) -> MemoryMapping | None:
        """The mapping containing address.

        Returns:
            The mapping whose [start, end) range contains address, or None
            if address falls in a gap or outside every mapping.
        """
        for mapping in self._mappings:
            if mapping.start <= address < mapping.end:
                return mapping
        return None

    def index_of(self, mapping: MemoryMapping) -> int:
        """mapping's position among mappings(), in listing order.

        Raises:
            ValueError: mapping is not one of this parser's mappings.
        """
        return self._mappings.index(mapping)

    @classmethod
    def _parse_line(cls, line: str) -> MemoryMapping:
        match = cls._LINE.match(line.strip())
        if match is None:
            raise ValueError(f"not a /proc/<pid>/maps line: {line!r}")
        return MemoryMapping(
            line=line.rstrip(),
            start=int(match[1], 16),
            end=int(match[2], 16),
            perms=match[3],
            offset=int(match[4], 16),
            dev=match[5],
            inode=int(match[6]),
            pathname=match[7].strip(),
        )
