"""A device process's memory map, read from /proc/<pid>/maps."""

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


class ProcMaps:
    """A device's /proc/<pid>/maps, read by pid or by process name.

    Args:
        shell: Shell the underlying pidof/cat commands run under; its user
            decides which processes' maps are readable.
    """

    def __init__(self, shell: Shell):
        self._shell = shell

    def by_pid(self, pid: int) -> bytes:
        """Read /proc/<pid>/maps.

        Returns:
            The file's exact bytes, as the device wrote them.

        Raises:
            NoSuchProcessError: pid has no /proc entry.
        """
        try:
            return self._shell.read_file(f"/proc/{pid}/maps")
        except FileNotFoundError:
            raise NoSuchProcessError(str(pid)) from None

    def by_name(self, name: str) -> bytes:
        """Resolve name to its sole pid, then read that pid's maps.

        Returns:
            The file's exact bytes, as the device wrote them.

        Raises:
            NoSuchProcessError: name matched no running process.
            AmbiguousProcessError: name matched more than one running process.
        """
        pids = self._shell.pidof(name)
        if not pids:
            raise NoSuchProcessError(name)
        if len(pids) > 1:
            raise AmbiguousProcessError(name, pids)
        return self.by_pid(pids[0])
