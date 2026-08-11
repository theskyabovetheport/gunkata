"""A running device command's stdout, delivered line by line as it arrives."""

import io
import subprocess
import weakref
from collections.abc import Iterator
from typing import IO

from .types import ShellError


class StreamConsumedError(RuntimeError):
    """A stream was iterated twice; it owns one process, which runs once."""


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

    _TERMINATE_GRACE_SECONDS = 5.0

    def __init__(
        self, command: str, process: subprocess.Popen, stderr_file: IO[bytes]
    ):
        if process.stdout is None:
            self._reap(process, stderr_file, self._TERMINATE_GRACE_SECONDS)
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
        self._finalizer = weakref.finalize(
            self, self._reap, process, stderr_file, self._TERMINATE_GRACE_SECONDS
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
            Idempotent. Safe to call from another thread or from inside the
            loop: it leaves stdout open while an iteration is live, because
            closing it underneath the reader would raise there instead of
            ending it. Terminating is enough to end the read, since the process
            dying closes the pipe.
        """
        if self._closed:
            return
        self._closed = True
        if self._process.poll() is None:
            self._stopped = True
        self._reap(self._process, None, self._TERMINATE_GRACE_SECONDS)
        self._stderr = self._drain_stderr()
        if not self._iterating:
            self._stdout.close()
        self._finalizer.detach()

    @staticmethod
    def _reap(
        process: subprocess.Popen, stderr_file: IO[bytes] | None, grace: float
    ) -> None:
        """Stop a process and wait for it, escalating if it ignores the request.

        Design:
            A command that traps SIGTERM would otherwise block the caller
            forever, and this runs from a ``finally`` where blocking strands the
            reader too. ``stderr_file`` is closed only when reaping on behalf of
            a dropped stream, which is the one path with nobody left to read it.
        """
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.wait()
        if stderr_file is not None and not stderr_file.closed:
            stderr_file.close()

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
            stderr is a temporary file rather than a pipe. A pipe caps at the
            OS buffer (~64KB); a command that filled it would block writing
            stderr, stop writing stdout, and deadlock a reader waiting on stdout.
            A file cannot block the writer, and hands the subprocess a real fd
            exactly as ``Shell.pull_file`` already does.
        """
        if self._stderr_file.closed:
            return self._stderr
        self._stderr_file.seek(0)
        raw = self._stderr_file.read()
        self._stderr_file.close()
        return raw.decode("utf-8", errors="replace").strip()

    def _raise_if_failed(self) -> None:
        """Refuse a command that failed rather than being stopped.

        Raises:
            ShellError: The command reported a non-zero exit status without this
                stream having asked it to stop.
        """
        if self._stopped:
            return
        if self._process.returncode != 0:
            raise ShellError(self._command, self._stderr, self._process.returncode)
