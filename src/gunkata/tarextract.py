"""Extracting a tar archive streamed off a device onto the local filesystem,
skipping only the members its safety filter refuses.
"""

import logging
import os
import tarfile

logger = logging.getLogger(__name__)


class TarExtractor:
    """Extracts a tar archive member by member into one destination directory.

    Args:
        ldir: Local directory every member lands under. Not created here --
            the caller ensures it exists first.

    Attributes:
        paths: Every local path that exists because of this extraction, in
            archive order.
        skipped: Every archive member this extraction refused or could not
            place, named as the archive named it.

    Design:
        Knows nothing about adb or the device: it takes a `tarfile.TarFile`
        already open over some binary stream, so every safety rule here is
        testable against a plain `BytesIO` archive, with no subprocess in
        the loop.
    """

    def __init__(self, ldir: str):
        self._ldir = ldir
        self.paths: list[str] = []
        self.skipped: list[str] = []

    def extract_all(self, archive: tarfile.TarFile) -> None:
        """Extract every member of archive, skipping the ones the filter refuses.

        Args:
            archive: An open `TarFile`, streaming or seekable.

        Raises:
            tarfile.TarError: Reading the next member's header failed --
                propagates uncaught, since it means the stream itself is
                broken, not that one member was unsafe.
            OSError: A local filesystem error (no space, permission denied)
                while writing a member -- propagates uncaught, since it is
                not something the filter has an opinion about.

        Design:
            Members are extracted one at a time rather than via
            `extractall`: `TarFile.errorlevel` defaults to 1, so a
            `FilterError` would abort `extractall` mid-stream, and a real
            device tree routinely holds a member the safe filter refuses on
            sight -- an absolute symlink (``lib -> /data/app/.../lib/arm64``)
            is common under `/data/app`. Per-member extraction is what makes
            "skip and report" possible instead of "abort entirely." Only
            `tarfile.FilterError` is caught here; every other exception a
            local write can raise travels the same path and must propagate.

            The filter runs here rather than inside `extract`, and `extract`
            is then handed its already-filtered result, so `paths` reports
            the name the member actually landed under. `data_filter` renames
            what it accepts -- it strips a leading separator rather than
            refusing it -- so re-deriving the landed path from the archive's
            own `member.name` would name a path outside ldir entirely, and
            `os.path.join` would drop ldir on the floor for an absolute one.
        """
        for member in archive:
            try:
                placed = self._filter(member, self._ldir)
            except tarfile.FilterError as refusal:
                logger.warning("skipping %s: %s", member.name, refusal)
                self.skipped.append(member.name)
                continue
            if placed is None:
                logger.warning(
                    "skipping %s: not a file, directory, or link", member.name
                )
                self.skipped.append(member.name)
                continue
            archive.extract(
                member,
                path=self._ldir,
                # placed is bound as a default so the filter cannot capture a
                # later iteration's member, though it is called before then.
                filter=lambda _member, _dest, placed=placed: placed,
            )
            target = os.path.normpath(os.path.join(self._ldir, placed.name))
            if os.path.lexists(target):
                self.paths.append(target)
            else:
                self.skipped.append(member.name)

    @staticmethod
    def _filter(member: tarfile.TarInfo, dest_path: str) -> tarfile.TarInfo | None:
        """Restore what a researcher pulled the tree to see, on top of the stdlib's own checks.

        Returns:
            None for a special file (device node, fifo, socket), which the
            caller records as skipped; otherwise the member as
            `tarfile.data_filter` would extract it -- renamed as that filter
            renames it, so its `name` is where the member lands -- with its
            recorded mode restored in full.

        Raises:
            tarfile.FilterError: `data_filter` refused the member -- an
                absolute path or link, or one that escapes `dest_path` via a
                symlink or ``..``.

        Design:
            Stock ``filter="data"`` raises `SpecialFileError` on a device
            node rather than skipping it, which would abort the whole pull;
            a device tree routinely contains one -- toybox tar happily
            archives `/dev/null`'s character-device entry. `data_filter`
            also clamps mode to ``& 0o755`` and strips higher bits;
            `replace` undoes only that clamping, so setuid bits and the
            member's real permissions survive. Ownership is left as
            `data_filter` set it -- a non-root local user cannot restore
            uid/gid regardless, so the report never implies a faithful copy
            of it.
        """
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            return None
        safe = tarfile.data_filter(member, dest_path)
        return safe.replace(mode=member.mode, deep=False)
