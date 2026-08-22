import gc
import signal
import subprocess
import tempfile
import threading
import time

import pytest

from gunkata import shell as shell_module
from gunkata.shell import ShellError, Stream, StreamConsumedError

_FOREVER = "while :; do echo tick; sleep 0.05; done"
_IGNORES_TERM = "trap '' TERM; while :; do echo tick; sleep 0.05; done"


def _stream(script: str) -> Stream:
    """A Stream over a local shell script, standing in for a device command.

    Real processes rather than a fake Popen: a fake could only confirm what we
    already believe about process lifetime, and these are the only tests that
    can prove a command never outlives its reader.

    The pipe keywords mirror Shell.stream exactly. If they drift, these tests
    stop covering the configuration that actually runs against a device.
    """
    stderr_file = tempfile.TemporaryFile(mode="w+b")
    process = subprocess.Popen(
        ["sh", "-c", script],
        stdout=subprocess.PIPE,
        stderr=stderr_file,
        stdin=subprocess.DEVNULL,
    )
    return Stream(script, process, stderr_file)


def test_yields_lines_without_trailing_newlines():
    assert list(_stream("echo one; echo two")) == ["one", "two"]


def test_natural_exhaustion_raises_shell_error_on_nonzero_exit():
    """A command that fails on its own must be loud, and must carry its stderr."""
    stream = _stream("echo one; echo went wrong >&2; exit 3")
    with pytest.raises(ShellError) as raised:
        list(stream)
    assert raised.value.rc == 3
    assert "went wrong" in raised.value.stderr


def test_early_break_terminates_the_process():
    """Breaking out of a followed command must reap it, not leak it."""
    stream = _stream(_FOREVER)
    for _ in stream:
        break
    assert stream._process.poll() is not None
    assert stream._process.returncode == -signal.SIGTERM


def test_early_break_does_not_raise_for_a_command_that_would_have_failed():
    """A stop the reader asked for is not a failure, whatever status follows it."""
    stream = _stream("echo one; echo two; exit 3")
    for _ in stream:
        break
    assert stream._process.returncode == 3


def test_exception_in_the_loop_body_still_reaps_the_process():
    """The caller's exception must surface unchanged, and the process must die."""
    stream = _stream(_FOREVER)
    with pytest.raises(ValueError, match="from the loop body"):
        for _ in stream:
            raise ValueError("from the loop body")
    assert stream._process.poll() is not None


def test_context_manager_closes_a_stream_that_was_never_iterated():
    stream = _stream(_FOREVER)
    with stream:
        pass
    assert stream._process.poll() is not None


def test_a_with_block_that_never_reads_a_line_still_reports_a_failure():
    """A command that fails entirely on its own must not be discarded unread.

    __exit__ used to close and stop there; a with-block that never iterates
    could then finish, fail, and nobody would ever know.
    """
    stream = _stream("exit 5")
    for _ in range(50):
        if stream._process.poll() is not None:
            break
        time.sleep(0.02)
    with pytest.raises(ShellError) as raised:
        with stream:
            pass
    assert raised.value.rc == 5


def test_a_with_block_that_never_reads_a_line_does_not_raise_on_success():
    with _stream("true") as stream:
        pass


def test_second_iteration_refuses_rather_than_yielding_nothing():
    """A spent stream must refuse: an empty stream reads like a quiet device."""
    stream = _stream("echo one")
    assert list(stream) == ["one"]
    with pytest.raises(StreamConsumedError):
        list(stream)


def test_a_sigterm_this_stream_did_not_send_is_reported_as_a_failure():
    """Discrimination is control flow, not a signal number.

    A process killed by someone else reaches end of output on its own, so it
    falls through to the failure check and stays loud. This test fails the
    moment anyone reimplements the rule as `if rc == -SIGTERM: return`, which
    would swallow an operator's kill and an OOM reaper alike.
    """
    stream = _stream("echo one; kill -TERM $$")
    with pytest.raises(ShellError) as raised:
        list(stream)
    assert raised.value.rc == -signal.SIGTERM


def test_close_from_another_thread_ends_the_loop_without_raising():
    """close() is a stop, so the status that follows it is not a failure.

    The reader unblocks at end of output and leaves the loop normally, which is
    the one stop that does not go through generator close. Discriminating on the
    signal number instead would report this stream's own SIGTERM as an error.
    """
    stream = _stream(_FOREVER)
    threading.Timer(0.3, stream.close).start()
    for _ in stream:
        pass
    assert stream._process.returncode == -signal.SIGTERM


def _pause_inside_reap(monkeypatch) -> tuple[threading.Event, threading.Event]:
    """Patch _reap so one caller can be pinned inside it while another runs.

    Returns:
        The event set once a reap has begun, and the event that releases it.

    Design:
        Call this only after the stream exists: __init__ passes _reap to
        weakref.finalize by value, so a stream built beforehand keeps the real
        one for its finalizer, while close() -- which looks the global up when
        it runs -- picks up the patched one.
    """
    reaping = threading.Event()
    finish = threading.Event()
    real_reap = shell_module._reap

    def blocking_reap(process, stderr_file, grace):
        reaping.set()
        finish.wait(5)
        return real_reap(process, stderr_file, grace)

    monkeypatch.setattr(shell_module, "_reap", blocking_reap)
    return reaping, finish


def test_close_does_not_return_until_a_racing_close_has_reaped(monkeypatch):
    """close() returning must mean the process was waited on, for every caller.

    Stream offers close as callable from another thread, so two threads reach
    it over one process. A second caller that returned on the _closed flag
    alone would leave the reader looking at a returncode of None, a _stopped
    still False, and no stderr.
    """
    stream = _stream("echo one; echo went wrong >&2; exit 3")
    reaping, finish = _pause_inside_reap(monkeypatch)
    closer = threading.Thread(target=stream.close)
    closer.start()
    assert reaping.wait(5), "the closing thread never entered _reap"
    threading.Timer(0.3, finish.set).start()

    stream.close()

    assert stream._process.returncode == 3
    assert "went wrong" in stream._stderr
    closer.join(5)


def test_a_racing_close_neither_swallows_a_failure_nor_invents_one(monkeypatch):
    """The reader's verdict must be the command's own, never an artifact of timing.

    Reading the stale returncode of None as a failure reports rc=None with no
    stderr, a value ShellError never means to carry; reading it as success
    discards a command that genuinely exited 3. Both are wrong, so this pins
    the real status and the real stderr reaching the caller.
    """
    stream = _stream("echo one; echo went wrong >&2; exit 3")
    reaping, finish = _pause_inside_reap(monkeypatch)
    closer = threading.Thread(target=stream.close)
    closer.start()
    assert reaping.wait(5), "the closing thread never entered _reap"
    threading.Timer(0.3, finish.set).start()

    with pytest.raises(ShellError) as raised:
        with stream:
            pass
    assert raised.value.rc == 3
    assert "went wrong" in raised.value.stderr
    closer.join(5)


def test_close_from_inside_the_loop_ends_it_without_raising():
    """Closing under a live read must end that read, never break it.

    Closing stdout beneath the reader would raise ValueError there instead.
    """
    stream = _stream(_FOREVER)
    for _ in stream:
        stream.close()
    assert stream._process.poll() is not None


def test_a_command_that_ignores_sigterm_is_killed(monkeypatch):
    """A trapped SIGTERM must not strand the reader in a finally block."""
    monkeypatch.setattr(shell_module, "_TERMINATE_GRACE_SECONDS", 0.5)
    stream = _stream(_IGNORES_TERM)
    for _ in stream:
        break
    assert stream._process.returncode == -signal.SIGKILL


def test_a_stream_that_is_never_iterated_still_reaps_its_process():
    """Spawning happens eagerly, so dropping a stream must not strand a command."""
    stream = _stream(_FOREVER)
    process = stream._process
    del stream
    gc.collect()
    assert process.poll() is not None


def test_an_undecodable_byte_is_replaced_rather_than_ending_the_stream():
    """A device logs whatever a native caller hands it; one bad byte is not fatal."""
    lines = list(_stream(r"printf 'before \377 after\nsecond\n'"))
    assert len(lines) == 2
    assert lines[0].startswith("before ") and lines[0].endswith(" after")


def test_a_carriage_return_stays_inside_its_line():
    """Only \\n ends a line; a \\r in a message must not forge a second one."""
    assert list(_stream(r"printf 'pro\rgress\n'")) == ["pro\rgress"]


def test_more_stderr_than_a_pipe_buffer_holds_does_not_deadlock():
    """stderr is a temp file, not a pipe; this pins that choice.

    A pipe caps at the OS buffer (~64KB): the command would block writing
    stderr, stop writing stdout, and a reader waiting on stdout would wait
    forever. If this test ever hangs, someone changed stderr back to a pipe.
    """
    stream = _stream("head -c 200000 /dev/zero | tr '\\0' 'x' >&2; echo done")
    assert list(stream) == ["done"]
