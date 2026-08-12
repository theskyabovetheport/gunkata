import logging
import os
import subprocess
import tempfile

from .adb import Adb
from .settings import SuBinary
from .stream import Stream
from .types import ShellError, ShellResult

logger = logging.getLogger(__name__)


class Shell:
    def __init__(self, adb: Adb, user: str | None, su: SuBinary):
        self._adb = adb
        self.user = user
        self.su = su

    def __call__(self, command: str) -> ShellResult:
        return self.sh(command)

    def sh(self, command: str, strip: bool = True) -> ShellResult:
        """Run a command on the device and wait for it to finish.

        Design:
            Captured in binary and decoded here rather than via ``text=True``:
            subprocess's text mode decodes strictly, so one undecodable byte
            would raise, and it translates a bare carriage return into a
            newline, which would split one line of device output into two.
            A device sends whatever a native caller hands it.
        """
        logger.debug("sh %s", command)
        cp = self._adb(["shell", self._su(command)], capture_output=True)
        stdout = cp.stdout.decode("utf-8", errors="replace")
        stderr = cp.stderr.decode("utf-8", errors="replace")
        if strip:
            stdout = stdout.rstrip()
            stderr = stderr.rstrip()
        result = ShellResult(
            command=command, stdout=stdout, stderr=stderr, rc=cp.returncode
        )
        logger.debug("sh %s -> %d", command, result.rc)
        return result

    def check_sh(self, command: str, strip: bool = True) -> ShellResult:
        result = self.sh(command, strip=strip)
        if not result.ok:
            raise ShellError(result.command, result.stderr, result.rc)
        return result

    def stream(self, command: str) -> Stream:
        """Follow a long-running device command, line by line as it produces output.

        Args:
            command: Command to run, wrapped as this shell's user via su.

        Returns:
            A single-use stream of the command's stdout lines, newlines
            stripped. The process is already running; the caller must exhaust,
            close, or ``with``-block the stream to reap it.

        Raises:
            OSError: The adb executable is not on PATH.

        Design:
            The streaming counterpart to ``sh``: same su wrapping, so a command
            behaves identically whether it is awaited or followed, and only
            delivery differs. stderr goes to a temporary file rather than a pipe
            so a chatty command cannot deadlock a reader waiting on stdout.
            stdin is closed so the device command never competes with the
            terminal for the user's keystrokes.

            The process is left in binary mode; Stream owns decoding, because
            subprocess offers no way to turn off universal newlines and a
            carriage return inside a log message must not forge a second line.

            The stderr file is closed here, not by Stream, if adb itself never
            starts: ownership only transfers to the Stream that is about to
            hold it, so a failed spawn must not leak the fd.
        """
        stderr_file = tempfile.TemporaryFile(mode="w+b")
        try:
            process = self._adb.popen(
                ["shell", self._su(command)],
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                stdin=subprocess.DEVNULL,
            )
        except BaseException:
            stderr_file.close()
            raise
        return Stream(command, process, stderr_file)

    def _su(self, command: str) -> str:
        return self.su.wrap(command, self.user)

    def _raise_if_failed(self, command: str, cp: subprocess.CompletedProcess) -> None:
        if cp.returncode == 0:
            return
        stderr = (
            cp.stderr
            if isinstance(cp.stderr, str)
            else (cp.stderr or b"").decode(errors="replace")
        )
        raise ShellError(command, stderr, cp.returncode)

    def dir_exists(self, dpath: str) -> bool:
        return self.sh(f"[ -d {dpath} ]").ok

    def file_exists(self, dpath: str) -> bool:
        return self.sh(f"[ -f {dpath} ]").ok

    def path_exists(self, dpath: str) -> bool:
        return self.sh(f"[ -e {dpath} ]").ok

    def pull_file(self, dpath: str, lpath: str):
        """Pull a file from the device to a local path.

        Args:
            dpath: Path on the device to read.
            lpath: Local path to create. Must not already exist.

        Raises:
            FileExistsError: lpath already exists.
            ShellError: The device command failed.

        Design:
            Written to a sibling temp file and published with os.link only on
            success, then the temp file is dropped. A failed transfer leaves
            nothing at lpath: no 0-byte file that could be mistaken for an
            empty remote file, and no leftover that would fail a retry with
            FileExistsError before the retry even starts.
        """
        command = f"cat {dpath}"
        tmp_path = f"{lpath}.gunkata-partial"
        try:
            with open(tmp_path, "wb") as fd:
                cp = self._adb(
                    ["shell", self._su(command)],
                    stdout=fd,
                    stderr=subprocess.PIPE,
                )
            self._raise_if_failed(command, cp)
            os.link(tmp_path, lpath)
        finally:
            os.remove(tmp_path)

    def push_file(self, dpath: str, lpath: str, inherit_owner: bool = True):
        command = f"cat >{dpath}"
        with open(lpath, "rb") as fd:
            cp = self._adb(
                ["shell", self._su(command)],
                stdin=fd,
                stderr=subprocess.PIPE,
            )
        self._raise_if_failed(command, cp)
        if inherit_owner:
            self.inherit_owner(dpath)

    _MISSING_FILE_RC = 90
    """Sentinel exit status read_file's command uses to report a missing path.

    Chosen clear of cat's own exit statuses (0, 1) and of the 128+ range a
    shell uses to report a signal, so it cannot collide with a real failure.
    """

    def read_file(self, dpath: str) -> bytes:
        """Read a file's raw bytes from the device.

        Raises:
            FileNotFoundError: dpath does not exist on the device.
            ShellError: The device command failed for any other reason.

        Design:
            The existence check is folded into the command itself, reported
            back as a sentinel exit status, rather than matched against cat's
            stderr text: that wording differs across toybox/busybox/coreutils
            builds and can be localized, so matching it would be one guess
            away from silently falling through to a plain ShellError.
        """
        command = (
            f"if [ -e {dpath} ]; then cat {dpath}; else exit {self._MISSING_FILE_RC}; fi"
        )
        cp = self._adb(["shell", self._su(command)], capture_output=True)
        if cp.returncode == self._MISSING_FILE_RC:
            raise FileNotFoundError(dpath)
        self._raise_if_failed(command, cp)
        return cp.stdout

    def write_file(self, dpath: str, data: bytes, *, inherit_owner: bool = True):
        command = f"cat >{dpath}"
        cp = self._adb(["shell", self._su(command)], input=data, capture_output=True)
        self._raise_if_failed(command, cp)
        if inherit_owner:
            self.inherit_owner(dpath, recursive=False)

    def inherit_owner(self, dpath: str, recursive: bool = True):
        """Chown dpath to its parent directory's owner.

        Args:
            recursive: Apply to dpath's contents too, for a directory just
                created rather than a single file already in place.
        """
        recursive_part = "-R " if recursive else ""
        command = f"chown {recursive_part}$(stat -c %u:%g $(dirname {dpath})) {dpath}"
        cp = self._adb(["shell", self._su(command)], capture_output=True)
        self._raise_if_failed(command, cp)

    def mkdir(self, dpath: str):
        self.check_sh(f"mkdir -p {dpath}")
        self.inherit_owner(dpath)

    def touch(self, dpath: str):
        self.check_sh(f"touch {dpath}")
        self.inherit_owner(dpath)

    def chown(self, dpath: str, user: str, group: str) -> None:
        self.check_sh(f"chown {user}:{group} {dpath}")

    def chmod(self, dpath: str, mode: str) -> None:
        self.check_sh(f"chmod {mode} {dpath}")

    def pidof(self, name: str) -> list[int]:
        result = self.sh(f"pidof {name}")
        return [int(pid) for pid in result.stdout.split()] if result.ok else []

    def execvp_sh(self, directory: str | None = None):
        """Replace this process with an interactive su shell on the device.

        Args:
            directory: Change to this directory on the device before
                attaching, rather than su's own starting directory.

        Design:
            Built through ``_su`` rather than its own su wrapping, so an
            interactive attach and a run-to-completion command can never mean
            two different things to su.

            ``os.execvp``, not ``subprocess``: this replaces the caller
            entirely so adb's own tty allocation (``shell -t``) stays
            attached to the caller's terminal directly, with nothing left of
            this process to relay it through.
        """
        cd = f"cd '{directory}' && " if directory else ""
        os.execvp(
            "adb",
            ["adb", "-s", self._adb.serial, "shell", "-t", self._su(f"{cd}exec sh")],
        )
