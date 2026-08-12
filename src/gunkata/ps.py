"""The device's process list, as `ps -A` reports it."""

from dataclasses import dataclass

from .shell import Shell


@dataclass(frozen=True)
class ProcessEntry:
    """One row of the device's process table.

    Attributes:
        pid: Process id.
        name: Command name ps reports for it.
    """

    pid: int
    name: str


class Ps:
    """The device's process list, fetched from `ps -A` and cached until refreshed.

    Args:
        shell: Shell the `ps` command runs under; its user decides which
            processes are visible.

    Design:
        A natural cache rather than a spent generator: the first call to
        entries() or names() runs `ps -A` once and holds the result, so a
        caller asking more than one question of the same snapshot -- name
        resolution and autocompletion both do -- pays for one device round
        trip rather than one per question. refresh() re-queries when the
        process list may have changed since.
    """

    def __init__(self, shell: Shell):
        self._shell = shell
        self._entries: list[ProcessEntry] | None = None

    def entries(self) -> list[ProcessEntry]:
        """Every running process.

        Returns:
            One entry per process, in the order `ps -A` reported them. Cached
            after the first call; call refresh() to see a since-changed list.

        Raises:
            ShellError: `ps -A` exited non-zero.
        """
        if self._entries is None:
            self._entries = self._fetch()
        return self._entries

    def refresh(self) -> list[ProcessEntry]:
        """Re-query the device's process list, replacing the cache.

        Returns:
            The freshly-fetched entries, same shape as entries().

        Raises:
            ShellError: `ps -A` exited non-zero.
        """
        self._entries = self._fetch()
        return self._entries

    def names(self) -> list[str]:
        """Every distinct process name currently running.

        Returns:
            Names in first-seen order, as entries() reported them, with
            duplicates -- multiple processes sharing a name -- collapsed.
        """
        seen: set[str] = set()
        names = []
        for entry in self.entries():
            if entry.name not in seen:
                seen.add(entry.name)
                names.append(entry.name)
        return names

    def _fetch(self) -> list[ProcessEntry]:
        """Run `ps -A` and parse its rows.

        Design:
            Parsed by column position, not by field count: PID is always the
            device's second column and NAME its last, across the toybox and
            procps `ps` builds Android has shipped, even though the column
            count between them differs. The header row is skipped by its
            leading field, ``USER``, for the same reason.
        """
        result = self._shell.check_sh("ps -A")
        entries = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if not fields or fields[0] == "USER":
                continue
            entries.append(ProcessEntry(pid=int(fields[1]), name=fields[-1]))
        return entries
