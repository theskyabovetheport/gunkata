"""The device's log buffers, read as a stream of parsed records."""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum

from .shell import Shell

logger = logging.getLogger(__name__)


class Level(IntEnum):
    """Priority logcat assigns a record.

    Design:
        Member names are the letters threadtime prints, so ``Level[letter]`` is
        the entire lookup and there is no mapping table to fall out of step with
        the format. Values are AOSP's ``android_LogPriority``, so comparing two
        levels orders them by the platform's severity rather than one invented
        here.

        ``__str__`` is overridden because IntEnum inherits int's, which would
        render the letter the device printed as its ordinal.
    """

    V = 2
    D = 3
    I = 4
    W = 5
    E = 6
    F = 7
    S = 8

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class LogcatEntry:
    """One record from an Android log buffer.

    Attributes:
        raw: The line exactly as the device delivered it.
        time: Month, day and wall clock to the millisecond, as the device
            printed it. threadtime prints no year and no zone.
        pid: Process that logged the record.
        tid: Thread within that process.
        level: Priority the record was logged at.
        tag: Subsystem that logged the record; empty when the device sent none.
        message: The record's text, colons and all.

    Design:
        Frozen because an entry is an observation. ``raw`` is the atom the
        device produced and every other field is a projection of it, so the two
        halves can never be edited into disagreement.

        ``time`` stays the string that was observed: threadtime carries neither
        a year nor a timezone, so building a ``datetime`` would mean inventing
        both. It becomes a real timestamp in the commit that also asks logcat
        for ``-v year -v UTC``.
    """

    raw: str
    time: str
    pid: int
    tid: int
    level: Level
    tag: str
    message: str


class Logcat:
    """The device's log buffers, iterable as parsed records.

    Args:
        shell: Shell the logcat process runs under; its user decides which
            buffers are readable.
        tail: How many already-buffered records to start from. None starts at
            the beginning of the ring buffer, which holds tens of thousands of
            records on a device that has been up a while.
        follow: Keep yielding records as the device writes them, rather than
            stopping at the end of what the buffer already holds.

    Raises:
        ValueError: tail is below one, which logcat cannot express.

    Design:
        A reusable spec rather than a spent generator: each iteration starts its
        own logcat, so the same object can be iterated more than once.

        ``tail`` defaults to 1 so a fresh iteration begins at the live tail.
        logcat's own default replays the whole ring buffer first -- measured at
        over twenty thousand lines on an idle emulator -- which would make
        "iterate until a line matches, then stop" match something logged hours
        ago, silently and wrongly.

        A line matching neither shape is logged and skipped rather than ending
        the stream. Any process on the device can write a tag containing a
        newline, which splits one record into two lines that match neither the
        record nor the marker pattern; raising there would hand every app on
        the device a way to kill a live tail with one log call.
    """

    _ENTRY = re.compile(
        r"^(?P<time>\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})"
        r" +(?P<pid>\d+) +(?P<tid>\d+)"
        r" (?P<level>[VDIWEFS])"
        r" (?P<tag>.*?): (?P<message>.*)$"
    )
    _MARKER = re.compile(r"^-+ beginning of \S+$")

    def __init__(self, shell: Shell, tail: int | None = 1, follow: bool = True):
        if tail is not None and tail < 1:
            raise ValueError(f"tail must be at least 1, got {tail}")
        self._shell = shell
        self._tail = tail
        self._follow = follow

    def __iter__(self) -> Iterator[LogcatEntry]:
        """Yield each record the device's log buffers produce.

        Yields:
            One record per iteration, in the order the device wrote it. Buffer
            markers are not records and do not appear. A followed stream ends
            only when its reader stops it.

        Raises:
            OSError: The adb executable is not on PATH.
            ShellError: logcat exited non-zero on its own -- an unreadable
                buffer, or a device that went away.
        """
        with self._shell.stream(self.command()) as stream:
            for line in stream:
                entry = self._parse(line)
                if entry is not None:
                    yield entry

    def command(self) -> str:
        """Build the logcat command line this spec runs on the device.

        Returns:
            One shell command line, always pinning threadtime so the requested
            format and the format the parser expects cannot disagree.

        Design:
            ``-t`` implies ``-d`` and ``-T`` does not, so mapping tail onto
            whichever matches ``follow`` leaves ``follow`` as the only option
            deciding whether iteration ever ends.
        """
        parts = ["logcat", "-v", "threadtime"]
        if self._tail is not None:
            parts += ["-T" if self._follow else "-t", str(self._tail)]
        elif not self._follow:
            parts.append("-d")
        return " ".join(parts)

    def _parse(self, line: str) -> LogcatEntry | None:
        """Read one line of ``logcat -v threadtime`` output.

        Args:
            line: One logcat output line, newline already stripped.

        Returns:
            The record the line carries, or nothing when the line is a buffer
            marker or a line this parser does not recognise.

        Design:
            An unrecognised line is logged at warning level rather than
            raised: any process on the device can force one by writing a tag
            containing a newline, and a stream that a hostile log entry can
            kill is a stream nobody can rely on. The warning still makes a
            genuine format change on some future Android audible, just not
            fatal to whoever is watching when it happens.

            The tag is right-stripped, never stripped: threadtime pads on the
            right only, so a leading space would belong to the tag itself. A tag
            that was empty on the device is served empty rather than filled in
            with a placeholder.
        """
        match = self._ENTRY.match(line)
        if match is not None:
            return LogcatEntry(
                raw=line,
                time=match["time"],
                pid=int(match["pid"]),
                tid=int(match["tid"]),
                level=Level[match["level"]],
                tag=match["tag"].rstrip(),
                message=match["message"],
            )
        if self._MARKER.match(line) is not None:
            return None
        logger.warning("unrecognised logcat line", extra={"line": line})
        return None
