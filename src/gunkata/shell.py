"""Running a command on a device: waited-for (``Shell.sh``) or followed line
by line as it produces output (``Shell.stream``), and the outcome types both
paths share.
"""

import io
import logging
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import threading
import weakref
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, NoReturn

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .adb import Adb
from .su import Su
from .tarextract import TarExtractor

logger = logging.getLogger(__name__)


class ShellSettings(BaseSettings):
    """Environment-resolved fields describing Device.shell's own defaulting.

    Attributes:
        default_user: The user a bare, argument-less `Device.shell()` call
            runs as. "shell" -- the default -- leaves such a command
            unwrapped; any other value runs it through su as that user, per
            Su.wrap.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    default_user: str = Field("shell", validation_alias="GUNKATA_SHELL_DEFAULT_USER")

    def resolve_user(self, user: str | None) -> str:
        """user if given, else this device's configured default_user."""
        return user if user is not None else self.default_user


class ShellError(RuntimeError):
    """A device command exited non-zero on its own.

    Args:
        command: The command as it was sent to the device, before su wrapping.
        stderr: Everything the command wrote to stderr.
        rc: The exit status the device reported.

    Design:
        Carries the three facts separately rather than a formatted string so a
        caller can branch on ``rc`` without re-parsing the message. A dropped
        adb transport reports rc 255 with empty stderr, so the message names the
        absence rather than trailing off after a bare colon.
    """

    def __init__(self, command: str, stderr: str, rc: int):
        self.command = command
        self.stderr = stderr
        self.rc = rc
        super().__init__(
            f"command {command!r} failed (rc={rc}): {stderr or '<no stderr>'}"
        )


@dataclass
class ShellResult:
    """The complete outcome of a device command that ran to completion.

    Attributes:
        command: The command as it was sent to the device, before su wrapping.
        stdout: Everything the command wrote to stdout.
        stderr: Everything the command wrote to stderr.
        rc: The exit status the device reported.
    """

    command: str
    stdout: str
    stderr: str
    rc: int

    @property
    def ok(self) -> bool:
        """Whether the command reported success."""
        return self.rc == 0

    @property
    def output(self) -> str:
        """Both streams concatenated, stdout first, with no separator inserted."""
        return f"{self.stdout}{self.stderr}"


class StreamConsumedError(RuntimeError):
    """A stream was iterated twice; it owns one process, which runs once."""


# _reap, _read_stderr, and the two timing constants below are module-level
# rather than methods, departing from the OOP-by-default convention on
# purpose: Stream and Shell.pull_tree are two owners of one process each,
# sharing one terminate -> grace -> kill policy, and there is no state to
# hang the functions on -- a class wrapping them would exist only to satisfy
# the rule.

_TERMINATE_GRACE_SECONDS = 5.0

_SETTLE_SECONDS = 0.1
"""Grace given a process that just closed its pipe to also become reapable.

Natural end-of-output and process exit are not one atomic event: the child
closes its stdout fd as part of exiting, which can be observed by a reader a
hair before the kernel finishes marking the process reapable. An
instantaneous ``poll()`` right at that instant can still read "running" for a
process that has, in fact, already exited on its own -- this closes that
window rather than trusting a zero-wait snapshot.
"""


def _reap(process: subprocess.Popen, stderr_file: IO[bytes] | None, grace: float) -> bool:
    """Stop a process and wait for it, escalating if it ignores the request.

    Returns:
        True if the process was still running and had to be signaled to
        stop; False if it had already exited or was exiting on its own.

    Design:
        A command that traps SIGTERM would otherwise block the caller
        forever, and this runs from a ``finally`` where blocking strands the
        reader too. ``stderr_file`` is closed only when reaping on behalf of
        a dropped stream, which is the one path with nobody left to read it.
    """
    try:
        process.wait(timeout=_SETTLE_SECONDS)
        still_running = False
    except subprocess.TimeoutExpired:
        still_running = True
    if still_running:
        process.terminate()
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if stderr_file is not None and not stderr_file.closed:
        stderr_file.close()
    return still_running


def _read_stderr(stderr_file: IO[bytes]) -> str:
    """Read everything written to stderr_file and close it.

    Returns:
        The command's stderr with surrounding whitespace removed; empty when
        it wrote nothing.

    Design:
        stderr is a temporary file rather than a pipe. A pipe caps at the
        OS buffer (~64KB); a command that filled it would block writing
        stderr, stop writing stdout, and deadlock a reader waiting on
        stdout. A file cannot block the writer, and hands the subprocess a
        real fd exactly as ``Shell.pull_file`` already does. Stripping lives
        here rather than in each caller: both consumers want it, and ``sh``
        already rstrips its own streams, so an unstripped ``ShellError``
        message would be the odd one out.
    """
    stderr_file.seek(0)
    raw = stderr_file.read()
    stderr_file.close()
    return raw.decode("utf-8", errors="replace").strip()


class Stream:
    """Lines of a running command's stdout, yielded as the command produces them.

    Args:
        command: The command as it was sent to the device, before su wrapping.
        process: The running process, started in binary mode. Ownership
            transfers to this stream, which terminates and reaps it.
        stderr_file: Open binary file the process writes stderr to. Ownership
            transfers to this stream, which reads and closes it.

    Raises:
        ValueError: process was not started with ``stdout=subprocess.PIPE``.

    Design:
        Single use, because the object wraps one specific process: a second
        iteration would silently yield nothing, and an empty stream is
        indistinguishable from a quiet device.

        No command outlives its reader. Leaving the loop -- break, an exception,
        or dropping the iterator -- terminates the process, and so does dropping
        a stream that was never iterated at all.

        Decoding is done here rather than by ``subprocess``, which offers no way
        to disable universal newlines: a device logs whatever a native caller
        hands it, so undecodable bytes are replaced instead of ending the
        stream, and only a newline ends a line, leaving a carriage return inside
        the message that carried it.
    """

    def __init__(
        self, command: str, process: subprocess.Popen, stderr_file: IO[bytes]
    ):
        if process.stdout is None:
            _reap(process, stderr_file, _TERMINATE_GRACE_SECONDS)
            raise ValueError("a stream's process needs stdout=subprocess.PIPE")
        self._command = command
        self._process = process
        self._stdout = io.TextIOWrapper(
            process.stdout, encoding="utf-8", errors="replace", newline="\n"
        )
        self._stderr_file = stderr_file
        self._stderr = ""
        self._consumed = False
        self._closed = False
        self._iterating = False
        self._stopped = False
        self._lock = threading.Lock()
        self._finalizer = weakref.finalize(
            self, _reap, process, stderr_file, _TERMINATE_GRACE_SECONDS
        )

    def __enter__(self) -> "Stream":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """Close the stream and, if nothing is propagating, report a failure.

        Design:
            A ``with``-block that never reads a line still owns the command it
            started: closing without checking would let a command that failed
            entirely on its own -- finished before the block even exited --
            pass for success. When an exception is already propagating, this
            defers to it rather than raising a second one over it.
        """
        self.close()
        if exc_type is None:
            self._raise_if_failed()

    def __iter__(self) -> Iterator[str]:
        """Yield each line the command writes to stdout, without its newline.

        Yields:
            One line per iteration, in the order the command wrote it. A
            followed command ends only when its reader stops it.

        Raises:
            StreamConsumedError: This stream was already iterated.
            ShellError: The command exited non-zero without this stream having
                stopped it.

        Design:
            Two mechanisms, because a reader can stop in two ways. Breaking out
            of the loop closes the generator, so ``finally`` runs and the check
            below is never reached. Calling ``close`` instead lets the loop end
            normally at end of output, so ``close`` records *that this stream
            asked to stop* and the check honours it. The question is never which
            signal ended the process -- a SIGTERM this stream did not send still
            reports as a failure, and the SIGKILL escalation below is not
            mistaken for one.
        """
        self._claim()
        self._iterating = True
        try:
            for line in self._stdout:
                yield line.rstrip("\n")
        finally:
            self._iterating = False
            self.close()
            self._stdout.close()
        self._raise_if_failed()

    def close(self) -> None:
        """Terminate the command if it is still running, and release its files.

        Design:
            Idempotent *and* blocking: a second caller waits for the first
            one's reap rather than returning while it is still in flight, so
            "close returned" means the same thing to whoever called it --
            the process has been waited on, and ``_stopped`` and ``_stderr``
            hold their final values.

            This class offers close as callable from another thread, and
            that promise is what needs the lock. Returning on the
            ``_closed`` flag alone would hand a racing caller all three
            still stale -- a ``returncode`` of ``None``, a ``_stopped``
            still False, an empty ``_stderr`` -- so its ``_raise_if_failed``
            would read a command that had failed on its own as one that
            never finished.

            A plain Lock rather than an RLock: the lock is only ever held
            across ``_reap`` and ``_drain_stderr``, which wait on the
            subprocess and its stderr file and never re-enter this stream.
            Holding it across ``_reap`` bounds a second caller's wait by
            ``_reap``'s own escalation to SIGKILL, not by the command.

            Safe to call from inside the loop as well: it leaves stdout open
            while an iteration is live, because closing it underneath the
            reader would raise there instead of ending it. Terminating is
            enough to end the read, since the process dying closes the pipe.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stopped = _reap(self._process, None, _TERMINATE_GRACE_SECONDS)
            self._stderr = self._drain_stderr()
            if not self._iterating:
                self._stdout.close()
            self._finalizer.detach()

    def _claim(self) -> None:
        """Take exclusive use of this stream.

        Raises:
            StreamConsumedError: This stream was already iterated.
        """
        if self._consumed:
            raise StreamConsumedError(
                f"stream for {self._command!r} was already consumed"
            )
        self._consumed = True

    def _drain_stderr(self) -> str:
        """Read everything the command wrote to stderr and close the file.

        Returns:
            The command's stderr with surrounding whitespace removed; empty when
            it wrote nothing, or when it was already drained.

        Design:
            A thin caching wrapper around the module-level ``_read_stderr``:
            the drained-once behavior is this stream's own state, not policy
            shared with any other reader, so it stays a method rather than
            moving out with ``_read_stderr`` itself.
        """
        if self._stderr_file.closed:
            return self._stderr
        return _read_stderr(self._stderr_file)

    def _raise_if_failed(self) -> None:
        """Refuse a command that failed rather than being stopped.

        Raises:
            ShellError: The command reported a non-zero exit status without this
                stream having asked it to stop.

        Design:
            Deliberately has no ``returncode is None`` branch. Both callers
            close first, and ``close`` does not return until the process has
            been waited on -- by them, or by the thread that beat them to it
            -- so ``None`` is unreachable here. Admitting it as "not failed"
            would silently swallow the failure of a command that had in fact
            exited non-zero; admitting it as a failure would report ``rc``
            as ``None``, which ``ShellError`` never means to carry. The fix
            for either belongs in ``close``, not in a branch here.
        """
        if self._stopped:
            return
        if self._process.returncode != 0:
            raise ShellError(self._command, self._stderr, self._process.returncode)


@dataclass
class PullResult:
    """The outcome of pulling a file, a directory tree, or a wildcard's matches.

    Attributes:
        paths: Every local path that exists because of this pull, in the
            order the device (or the archive) produced them. A plain-file
            pull lands exactly one; a wildcard lands one per match, flat; a
            directory lands its tree's root first and then its contents.
        skipped: Every archive entry the extraction filter refused, named as
            the device named it; always empty for a plain-file pull.

    Design:
        ``skipped`` carries names only: the reason each was refused goes to
        ``logger.warning`` at the point of refusal, since a list of
        ``(name, reason)`` pairs would breach the one-level generic-nesting
        limit and a caller only ever prints the names.
    """

    paths: list[str]
    skipped: list[str]


class Shell:
    def __init__(
        self,
        adb: Adb,
        user: str | None,
        su: Su,
        settings: ShellSettings | None = None,
    ):
        """Bind to adb as user, or to settings' configured default_user when user is None.

        Args:
            user: The user to run commands as, or None for the unqualified
                default: settings.default_user.
            settings: This device's resolved ShellSettings, or None to
                resolve fresh ones from the environment -- the same
                settings-or-None shape Su.__init__ takes for su.
        """
        self._adb = adb
        self.su = su
        # pyright can't see the env-backed default through validation_alias.
        self.user = (settings or ShellSettings()).resolve_user(user)  # pyright: ignore

    @property
    def serial(self) -> str:
        return self._adb.serial

    def __call__(self, command: str) -> ShellResult:
        return self.sh(command)

    def _run(self, command: str) -> subprocess.CompletedProcess:
        """Run command on the device and capture its output, stdin closed.

        Design:
            stdin=DEVNULL so a one-shot command never forwards this
            process's own stdin to the device: adb otherwise pumps
            whatever's on it to the remote command, draining it out from
            under a caller that means to read it itself afterward (a
            command's own -p/-P resolution shelling out to pidof before
            reading a payload from stdin, say). Same reasoning
            ``_popen_command``'s docstring gives for its streaming
            commands, applied to adb's synchronous, capture_output form.
            write_file/write_bytes call ``self._adb`` directly instead of
            this, since their own ``input=`` already supplies stdin.
        """
        return self._adb(
            ["shell", self._su(command)], capture_output=True, stdin=subprocess.DEVNULL
        )

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
        cp = self._run(command)
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
            delivery differs. See ``_spawn`` for the process it wraps.
        """
        return Stream(command, *self._spawn(command))

    def _spawn(self, command: str) -> tuple[subprocess.Popen, IO[bytes]]:
        """Start command on the device without waiting for it, stdout piped.

        Returns:
            The running process, stdout in binary mode via
            ``stdout=subprocess.PIPE``, and the open stderr file it writes
            to. Ownership of both transfers to the caller, which must reap
            the process and close the file.

        Raises:
            OSError: The adb executable is not on PATH.

        Design:
            Shared by ``stream`` and ``Shell.pull_tree``, the two consumers
            that read a device command's output as it arrives rather than
            waiting for it to finish. stderr goes to a temporary file rather
            than a pipe so a chatty command -- tar on a big tree logs one
            ``Permission denied`` line per unreadable file -- cannot deadlock
            a reader waiting on stdout. stdin is closed so the device command
            never competes with the terminal for the user's keystrokes.

            The process is left in binary mode; decoding, if any, is the
            caller's job -- ``Stream`` does its own because subprocess offers
            no way to turn off universal newlines, and a carriage return
            inside a log message must not forge a second line.

            The stderr file is closed here, not by the caller, if adb itself
            never starts: ownership only transfers once spawning succeeds, so
            a failed spawn must not leak the fd.
        """
        stderr_file = tempfile.TemporaryFile(mode="w+b")  # noqa: SIM115 -- outlives this scope
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
        return process, stderr_file

    def _su(self, command: str) -> str:
        return self.su.wrap(command, self.user)

    _WILDCARD_CHARACTERS = "*?["
    """Characters that make a device path's basename a glob pattern rather
    than a literal name, per `pull`'s dispatch."""

    @classmethod
    def _is_wildcard(cls, name: str) -> bool:
        return any(char in name for char in cls._WILDCARD_CHARACTERS)

    _SAFE_DEVICE_PATH = re.compile(r"^(?:[A-Za-z0-9._/@%+=,:~^!*?\[\]-]|[^\x00-\x7F])+$")
    """Characters `pull` accepts in a device path before it reaches
    the device's own shell unquoted.

    Follows `_DEVICE_PATH` in `frida/server.py`, widened: that narrower class
    would refuse real APK paths such as `/data/app/~~5Hqa==/pkg-1==/base.apk`.
    Non-ASCII bytes are admitted because an `/sdcard` filename is whatever an
    app wrote it as. Absent on purpose: space, backslash, both quotes, `$`,
    backtick, `;`, `&`, `|`, `<`, `>`, `(`, `)`, `{`, `}`, `#`.

    A whitelist rather than quoting, because quoting would defeat the
    feature: the device's shell is what expands the wildcard, so dpath is
    spliced unquoted into `_TAR_STREAM_COMMAND`'s own shell syntax.
    `Su.wrap` escapes the assembled command for su's inner shell, but that
    protects the su hop, not this splice -- `adb shell` hands the command to
    a shell whether su is involved or not.

    Only `pull` validates against this; `push_file`/`read_file`/`write_file`
    stay unvalidated, so this is not yet a `Shell`-wide invariant.

    Matched with `fullmatch`, never `match`: Python's `$` also matches just
    before a trailing newline, so `match` would accept `/x/foo\\n` -- one
    newline past the end of a whitelist whose whole purpose is to keep shell
    syntax out of a raw-interpolated command.
    """

    def _check_device_path(self, dpath: str) -> None:
        """Refuse a device path before it is spliced into a device command.

        Raises:
            ValueError: dpath holds a character outside _SAFE_DEVICE_PATH;
                carries a wildcard outside its final component; is "/" and so
                has no basename to pull; or is not absolute.

        Design:
            Accepting wildcard patterns makes `pull`'s raw interpolation of
            dpath into a device command load-bearing rather than incidental,
            so this is the point that states and guards it, once, before any
            I/O. A wildcard outside the last component is refused rather than
            resolved on the device: `cd /d*` with several matches gives `cd:
            too many arguments` but silently succeeds with exactly one, so
            behavior would depend on how many matches happened to exist.
            "/" is the only path with an empty basename -- `PurePosixPath`
            normalizes a trailing slash, so `/data/data/com.foo/` yields
            basename `com.foo` and pulls exactly as the slashless form does.
            A relative path is refused because `cd` resolves it differently
            once `Su.wrap` has already changed the su session's directory.
        """
        if not self._SAFE_DEVICE_PATH.fullmatch(dpath):
            raise ValueError(
                f"unsafe device path {dpath!r}: shell metacharacters are refused, not quoted"
            )
        path = PurePosixPath(dpath)
        if any(self._is_wildcard(part) for part in path.parts[:-1]):
            raise ValueError(
                f"wildcard outside the last component of {dpath!r}: "
                "pull the parent directory instead"
            )
        if not path.name:
            raise ValueError(f"device path {dpath!r} has no basename to pull")
        if not path.is_absolute():
            raise ValueError(f"device path {dpath!r} is not absolute")

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

    def pull(self, dpath: str, lpath: str | None = None) -> PullResult:
        """Pull a file, a directory tree, or a wildcard's matches from the device.

        Args:
            dpath: Device path to pull. A wildcard in its final component
                pulls every match; otherwise a directory pulls its whole
                tree, and anything else pulls the single file it names.
            lpath: Local destination, or None to default to the current
                directory. For a plain file this is the file itself, or its
                parent when it already names an existing local directory;
                for a wildcard or a directory this is always the parent
                directory the matches or the tree land under -- never
                renamed onto the remote name.

        Returns:
            The pull's outcome; see PullResult.

        Raises:
            ValueError: dpath failed validation; see _check_device_path.
            FileNotFoundError: dpath names neither a file nor a directory on
                the device, a wildcard matched nothing, or the local
                destination directory does not exist.
            NotADirectoryError: lpath exists and is not a directory (tree or
                wildcard case only).
            IsADirectoryError: lpath resolves to an existing local directory
                for the file case; see pull_file.
            ShellError: The device command failed for any other reason.

        Design:
            Dispatches on syntax before any round trip: a wildcard in the
            basename always means tar, decided from dpath alone, with no
            probe. Everything else costs exactly one probe that answers
            file/directory/missing at once, rather than a `[ -f ]` then
            `[ -d ]` pair -- a plain file never reaches tar, and a missing
            path raises FileNotFoundError from that same probe rather than a
            ShellError, which is the one behavior change from the old
            file-only `pull_file`-via-`cat` path. The existing-local-
            directory rule for the file case lives here, not in pull_file,
            so pull_file stays exactly as it was -- its own IsADirectoryError
            survives as the last-resort guard for when lpath/<basename> is
            itself a directory.

            No local directory is ever created to receive a pull, in any of
            the three cases: a destination that does not exist is a refusal
            naming it, not a mkdir. A mistyped destination is otherwise
            silently correct -- `pull /data/data/com.foo ~/wrok` would report
            success and leave the tree somewhere nobody looks -- and the file
            case could not offer the convenience anyway, since it writes
            through a spool file its parent must already hold. Directories
            *inside* an extracted tree are content, not destination, and are
            created as the archive names them.
        """
        self._check_device_path(dpath)
        name = PurePosixPath(dpath).name
        if self._is_wildcard(name):
            return self.pull_tree(dpath, lpath if lpath is not None else os.getcwd())
        kind = self.sh(
            f"if [ -f {dpath} ]; then echo f; elif [ -d {dpath} ]; then echo d; "
            "else echo n; fi"
        ).stdout
        if kind == "d":
            return self.pull_tree(dpath, lpath if lpath is not None else os.getcwd())
        if kind != "f":
            raise FileNotFoundError(f"no such path on the device: {dpath}")
        if lpath is None:
            target = os.path.join(os.getcwd(), name)
        elif os.path.isdir(lpath):
            target = os.path.join(lpath, name)
        else:
            target = lpath
        parent = os.path.dirname(target) or "."
        if not os.path.isdir(parent):
            raise FileNotFoundError(
                f"local destination directory does not exist: {parent}"
            )
        self.pull_file(dpath, target)
        return PullResult(paths=[target], skipped=[])

    _TAR_STREAM_COMMAND = (
        'cd {parent} && {{ set -- ./{pattern}; [ -e "$1" ] || [ -h "$1" ] '
        '|| exit {missing_rc}; tar -cf - "$@"; }}'
    )
    """Device command shared by a directory pull and a wildcard pull.

    Every piece earns its place:

    - The `{ ...; }` braces are mandatory: `cd X && A; B` runs B even when
      cd fails, since `&&` binds only the next command, so without them a
      failed cd would still run tar in the wrong directory. cd's own failure
      is not folded into the sentinel -- it surfaces as a real ShellError
      carrying cd's own stderr ("No such file or directory" vs "Permission
      denied"), which a sentinel would discard.
    - The `./` prefix means a basename starting with `-` can never be read
      as a tar option, and one starting with `~` can never be tilde-expanded
      -- real Android app directories are named `~~5Hqa==`.
    - `[ -h "$1" ]` covers a glob whose first match is a dangling symlink,
      where `-e` is false; without it the pull would raise a lying
      FileNotFoundError.
    - `"$@"`, never `$*`: this command reaches the device as one shell word,
      so the double quotes arrive intact and `$@` expands where it should.

    The template holds no single quote, on purpose: `Su.wrap` escapes what it
    substitutes, so a quote here would merely survive as itself, but keeping
    the command quote-free means it reads the same whether it went through su
    or not.
    """

    def pull_tree(self, dpath: str, ldir: str) -> PullResult:
        """Pull a device directory's tree, or a wildcard's matches, into ldir.

        Args:
            dpath: Directory or wildcard device path to pull. Validated by
                this method itself -- see _check_device_path -- since dpath
                is interpolated unescaped into a device command and a public
                method cannot rely on its caller having checked it first.
            ldir: Local directory to extract into, which must already exist. A
                directory pull lands under ldir/<basename of dpath>; a
                wildcard's matches land flat inside ldir itself.

        Returns:
            The pull's outcome; see PullResult.

        Raises:
            ValueError: dpath failed validation; see _check_device_path.
            NotADirectoryError: ldir exists and is not a directory.
            FileNotFoundError: ldir does not exist, or dpath's pattern
                matched nothing on the device.
            ShellError: The device command failed for any other reason --
                whatever landed before the failure stays on disk.
            tarfile.TarError: The stream could not be parsed as a tar
                archive and the device command itself exited zero.

        Design:
            One shape covers both callers: `_TAR_STREAM_COMMAND` cds into
            dpath's parent and tars `./<pattern>` -- a directory's own name
            for a directory pull, a glob for a wildcard pull -- so a tar
            member's own path decides whether it lands flat (a glob, whose
            matches have no directory component) or nested under a name (a
            directory, whose members are all `<name>/...`).

            Never `wait()` on the process before closing or draining its
            stdout -- that deadlocks a device command still writing into a
            full pipe. On a clean parse, the archive is read to its logical
            end and then drained of any trailing padding before reaping; on
            a broken parse, `proc.stdout` is closed instead, so the writer
            gets EPIPE rather than being waited on.

            The exit status decides what a caught TarError actually meant --
            never the parse error itself. A glob matching nothing makes the
            device command `exit 90` before tar ever runs, which starves
            tarfile of any data and raises `ReadError: empty file`; the
            honest error is FileNotFoundError, read off the sentinel rc, not
            the misleading parse failure. A missing parent directory raises
            the same ReadError with rc 2 and cd's own real message, so it
            surfaces as a ShellError carrying that stderr instead. `rc > 0`,
            not `rc != 0`, decides both: on the broken-parse path stdout was
            closed deliberately, so a negative returncode (-SIGPIPE, or
            -SIGTERM from _reap's escalation) is this cleanup's own doing,
            not the device's verdict.

            A clean parse can still end in failure: toybox tar refuses a
            socket, does not name it, and exits rc 1 while archiving
            everything else correctly -- so rc is checked even when no
            TarError was ever raised. What already landed is kept and
            returned to the caller only via the raised ShellError's log line,
            not the return value, since the pull as a whole did not succeed.
        """
        self._check_device_path(dpath)
        if not os.path.exists(ldir):
            raise FileNotFoundError(f"local destination directory does not exist: {ldir}")
        if not os.path.isdir(ldir):
            raise NotADirectoryError(ldir)

        path = PurePosixPath(dpath)
        command = self._TAR_STREAM_COMMAND.format(
            parent=path.parent, pattern=path.name, missing_rc=self._MISSING_FILE_RC
        )
        process, stderr_file = self._spawn(command)
        assert process.stdout is not None, "_spawn always passes stdout=PIPE"
        extractor = TarExtractor(ldir)
        broken: tarfile.TarError | None = None
        try:
            with tarfile.open(mode="r|", fileobj=process.stdout, errorlevel=1) as archive:
                extractor.extract_all(archive)
            process.stdout.read()
        except tarfile.TarError as exc:
            broken = exc
            process.stdout.close()

        _reap(process, None, _TERMINATE_GRACE_SECONDS)
        stderr = _read_stderr(stderr_file)
        rc = process.returncode

        if broken is not None:
            if rc == self._MISSING_FILE_RC:
                raise FileNotFoundError(
                    f"nothing on the device matches: {dpath}"
                ) from broken
            if rc > 0:
                raise ShellError(command, stderr, rc) from broken
            raise broken

        destination = ldir if self._is_wildcard(path.name) else os.path.join(ldir, path.name)
        if rc > 0:
            retry_hint = " -- retry with -U root" if "Permission denied" in stderr else ""
            logger.warning(
                "pull of %s into %s failed partway (rc=%d): %d entries landed, "
                "the tree is incomplete%s",
                dpath,
                destination,
                rc,
                len(extractor.paths),
                retry_hint,
            )
            raise ShellError(command, stderr, rc)

        return PullResult(paths=extractor.paths, skipped=extractor.skipped)

    def pull_file(self, dpath: str, lpath: str):
        """Pull a file from the device to a local path, replacing it if it exists.

        Args:
            dpath: Path on the device to read.
            lpath: Local path to write. An existing file there is replaced.

        Raises:
            IsADirectoryError: lpath is a directory.
            ShellError: The device command failed.

        Design:
            Written to a sibling ``<lpath>.gk-part`` file first, published by
            renaming onto lpath only once the transfer succeeds. os.rename is
            a single atomic syscall on a POSIX filesystem, so lpath itself is
            never observed partial: it holds either its previous contents (the
            transfer failed or was interrupted, or it did not exist and stays
            absent) or the complete pull, never a mix of the two.

            A directory at lpath is refused up front rather than left to
            os.rename, which would raise only after the whole transfer had
            been spooled to a ``.gk-part`` beside it.

            On failure, an empty ``.gk-part`` (the command failed before
            writing anything) is removed silently; a non-empty one is kept
            rather than discarded, since it may hold data worth rescuing by
            hand, and its path is logged as a warning so the failure is loud
            rather than a silent file left for the caller to stumble on
            later. The broad ``except BaseException`` is a cleanup boundary,
            not a resilience one -- it always re-raises the original error,
            it just decides the partial file's fate first.
        """
        if os.path.isdir(lpath):
            raise IsADirectoryError(lpath)
        command = f"cat {dpath}"
        tmp_path = f"{lpath}.gk-part"
        try:
            with open(tmp_path, "wb") as fd:
                cp = self._adb(
                    ["shell", self._su(command)],
                    stdout=fd,
                    stderr=subprocess.PIPE,
                )
            self._raise_if_failed(command, cp)
        except BaseException:
            if os.path.exists(tmp_path):
                if os.path.getsize(tmp_path) == 0:
                    os.remove(tmp_path)
                else:
                    logger.warning(
                        "pull of %s failed partway; partial data kept at %s",
                        dpath,
                        tmp_path,
                    )
            raise
        os.rename(tmp_path, lpath)

    def push_file(self, dpath: str, lpath: str, inherit_owner: bool = True):
        """Push a local file to the device.

        Args:
            dpath: Path on the device to write. A directory there receives the
                file under lpath's own basename, as ``cp`` and ``adb push`` do.
            lpath: Local file to read.
            inherit_owner: Chown the written file to its parent directory's
                owner, rather than leaving it owned by whoever the push ran as.

        Raises:
            OSError: lpath is not a readable file.
            ShellError: The device command failed.

        Design:
            The directory case costs one extra round trip on every push, and
            is resolved here rather than by the caller because only the device
            knows whether dpath is a directory. Without the check, ``cat
            >/some/dir`` would fail with the shell's own redirect error, which
            names neither the file nor the mistake.
        """
        if self.dir_exists(dpath):
            dpath = str(PurePosixPath(dpath) / Path(lpath).name)
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
        cp = self._run(command)
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
        cp = self._run(command)
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

    def read_bytes(self, command: str) -> bytes:
        """Run command and return its raw, unstripped stdout bytes.

        Raises:
            ShellError: command exited non-zero.

        Design:
            Bypasses ``sh``'s text decoding and stripping: a caller reading
            binary content -- a memory dump, here -- needs every byte
            untouched, and stripping trailing whitespace would silently
            drop bytes that happen to look like it.
        """
        cp = self._run(command)
        self._raise_if_failed(command, cp)
        return cp.stdout

    def write_bytes(self, command: str, data: bytes) -> None:
        """Run command with data piped to its stdin.

        Raises:
            ShellError: command exited non-zero.
        """
        cp = self._adb(["shell", self._su(command)], input=data, capture_output=True)
        self._raise_if_failed(command, cp)

    def execvp_sh(
        self,
        command: str | None = None,
        directory: str | None = None,
        pty: bool = True,
    ) -> NoReturn:
        """Replace this process with adb, running command or attaching a shell.

        Args:
            command: Run this on the device and exit with its status; when
                None, attach an interactive shell instead.
            directory: Change to this directory on the device first, rather
                than su's own starting directory.
            pty: Ask adb for a device pty (its ``-t``).

        Raises:
            OSError: The adb executable is not on PATH.

        Design:
            A command execs too, rather than being captured and echoed once it
            finishes: a captured command shows nothing until it exits, so one
            that never exits (``top``, ``logcat``) shows nothing at all, and
            one that draws a UI has no terminal to draw on. Exit status, both
            streams and stdin pass through adb on their own, leaving nothing
            for this process to relay -- which is the whole reason to exec
            rather than to wrap.

            A pty is the caller's decision, not this method's: it is what
            gives a full-screen program its window size and its keys
            unbuffered, but it also merges stderr into stdout and translates
            newlines, so a caller with either stream redirected wants none.

            Built through ``_su`` rather than its own su wrapping, so an
            interactive attach and a run-to-completion command can never mean
            two different things to su.

            directory is shlex.quote'd here, not hand-wrapped in ``'...'``:
            this method assembles the inner command string itself, so a
            directory containing its own single quote is this method's own
            responsibility to escape correctly, not something downstream can
            fix after the fact.
        """
        cd = f"cd {shlex.quote(directory)} && " if directory else ""
        argv = ["adb", "-s", self._adb.serial, "shell"]
        if pty:
            argv.append("-t")
        argv.append(self._su(f"{cd}{command or 'exec sh'}"))
        os.execvp("adb", argv)
