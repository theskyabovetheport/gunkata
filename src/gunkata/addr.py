"""Where a set of addresses falls among a /proc/<pid>/maps listing."""

import re
from dataclasses import dataclass


@dataclass
class _Mapping:
    """One line of a /proc/<pid>/maps listing.

    Attributes:
        start: Start address of the mapping.
        end: End address of the mapping, exclusive.
        line: The line exactly as it was read, trailing whitespace stripped.
    """

    start: int
    end: int
    line: str


class AddrLocator:
    """Locates addresses among a /proc/<pid>/maps listing and annotates it.

    Args:
        maps_text: The listing, exactly as /proc/<pid>/maps or `gunkata
            procmaps` produced it.

    Raises:
        ValueError: A non-blank line doesn't start with an ``<start>-<end>``
            hex range.

    Design:
        Annotations accumulate against mapping *lines*, not addresses -- one
        mapping can gain notes from several locate() calls -- so rendering is
        a single pass over the original lines, each answer inserted next to
        the line it describes rather than collected separately and re-sorted
        against it.
    """

    _RANGE = re.compile(r"^([0-9a-f]+)-([0-9a-f]+)")

    def __init__(self, maps_text: str):
        self._mappings = [
            self._parse_line(line) for line in maps_text.splitlines() if line.strip()
        ]
        self._notes: dict[int, list[str]] = {}

    @staticmethod
    def parse_address(spec: str) -> int:
        """Parse a `-a` address expression: hex terms joined by `+` and `-`.

        Args:
            spec: e.g. ``"7fffc274f000"``, ``"0x7fffc274f000+0x1000"``, or
                ``"0x7fffc274f000+0x2000-0x1000"``. Each term may carry a
                ``0x`` prefix or not; a term with no leading sign is added.

        Returns:
            The address the expression names.

        Raises:
            ValueError: A term is not valid hex.
        """
        total = 0
        sign = 1
        for token in re.split(r"([+-])", spec):
            token = token.strip()
            if not token:
                continue
            if token == "+":
                sign = 1
            elif token == "-":
                sign = -1
            else:
                total += sign * int(token, 16)
        return total

    def locate(self, address: int) -> None:
        """Record where address falls, to be rendered by annotated().

        Args:
            address: The address to locate among this listing's mappings.

        Design:
            Mappings are walked in the ascending order /proc/<pid>/maps
            already lists them in. The first mapping address doesn't precede
            is either the one that contains it or the one right after the gap
            it falls in -- there's no third case to check for, because
            anything closer would have matched containment on an earlier
            mapping already.
        """
        if not self._mappings:
            return
        for index, mapping in enumerate(self._mappings):
            if mapping.start <= address < mapping.end:
                self._note(index, self._describe("contained", mapping, address))
                return
            if address < mapping.start:
                if index > 0:
                    above = self._mappings[index - 1]
                    self._note(index - 1, self._describe("below", above, address))
                self._note(index, self._describe("above", mapping, address))
                return
        last = self._mappings[-1]
        self._note(len(self._mappings) - 1, self._describe("below", last, address))

    def annotated(self, before: int = 3, after: int = 3) -> str:
        """Render each noted mapping's line, with context lines around it.

        Args:
            before: How many mapping lines to include above (preceding) each
                noted mapping, like grep -B.
            after: How many mapping lines to include below (following) each
                noted mapping, like grep -A.

        Returns:
            One block per noted mapping (or run of overlapping ones), each
            line unchanged except that a noted mapping gains a trailing
            ``  // note; note`` comment. Blocks that aren't adjacent are
            separated by a bare ``--`` line, as grep -A/-B do. Empty when
            nothing was located.

        Design:
            Nothing located means nothing printed, not the whole listing:
            this mirrors grep, where a pattern that matches nothing yields no
            output regardless of -A/-B.
        """
        windows = []
        for index in sorted(self._notes):
            lo = max(0, index - before)
            hi = min(len(self._mappings) - 1, index + after)
            if windows and lo <= windows[-1][1] + 1:
                windows[-1] = (windows[-1][0], max(windows[-1][1], hi))
            else:
                windows.append((lo, hi))

        lines = []
        for window_index, (lo, hi) in enumerate(windows):
            if window_index > 0:
                lines.append("--")
            for index in range(lo, hi + 1):
                mapping = self._mappings[index]
                notes = self._notes.get(index)
                line = (
                    f"{mapping.line}  // {'; '.join(notes)}" if notes else mapping.line
                )
                lines.append(line)
        return "".join(f"{line}\n" for line in lines)

    def _note(self, index: int, note: str) -> None:
        self._notes.setdefault(index, []).append(note)

    def _parse_line(self, line: str) -> _Mapping:
        match = self._RANGE.match(line)
        if match is None:
            raise ValueError(f"not a /proc/<pid>/maps line: {line!r}")
        return _Mapping(
            start=int(match[1], 16), end=int(match[2], 16), line=line.rstrip()
        )

    @classmethod
    def _describe(cls, label: str, mapping: _Mapping, address: int) -> str:
        """Describe address relative to the one of mapping's edges label cares about.

        Returns:
            ``"<label> <+/-><offset>"``: "below" reports its distance past
            the mapping's end, "above" its distance before the mapping's
            start -- the edge the gap actually touches. "contained" reports
            both, start's offset then end's, since neither alone places
            address inside the mapping. Each offset's magnitude is
            non-negative; only its sign says whether address sits after (+)
            or before (-) that edge.
        """
        if label == "below":
            return f"{label} {cls._relative(address - mapping.end)}"
        if label == "above":
            return f"{label} {cls._relative(address - mapping.start)}"
        start_offset = cls._relative(address - mapping.start)
        end_offset = cls._relative(address - mapping.end)
        return f"{label} {start_offset} {end_offset}"

    _ADDRESS_SPACE_SIZE = 1 << 64

    @classmethod
    def _relative(cls, delta: int) -> str:
        """Render delta as a signed hex offset: ``+0x10`` or ``-0x10``, never ``+-0x10``.

        Design:
            Addresses are 64-bit, so the meaningful distance between two of
            them is the shorter of the two paths around a 2**64 ring, not the
            raw difference: x86_64's canonical hole puts the vsyscall page a
            genuine ~2**64 away from userspace by raw subtraction, when the
            two are really one small hop apart if you go the other way round.
            Direction keeps delta's own sign either way -- going the short
            way around doesn't put address on the other side of the edge.
        """
        magnitude = abs(delta)
        magnitude = min(magnitude, cls._ADDRESS_SPACE_SIZE - magnitude)
        return f"{'+' if delta >= 0 else '-'}0x{magnitude:x}"
