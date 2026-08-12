import threading
import time
import uuid

import pytest

from gunkata.logcat import Level, Logcat
from gunkata.types import ShellError

# Real lines taken verbatim from a live emulator; each pins a shape the
# threadtime format actually produces.
_PLAIN = "08-10 21:32:22.469   546   676 E WifiScoringParams: Invalid frequency(-1)"
_PADDED_TAG = "08-10 21:33:20.429     0     0 W healthd : battery l=100 v=5000"
_EMPTY_TAG = "08-10 20:58:50.934     0     0 I         : Stack Depot is disabled"
_COLONS = "08-10 20:58:52.084     0     0 I pci 0000: 00:01.1: legacy IDE quirk"
_MARKER = "--------- beginning of main"


class _FakeStream:
    """Hands back canned lines in place of a live device command."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, *_exc_info) -> None:
        return None

    def __iter__(self):
        return iter(self._lines)


class _FakeShell:
    """Stands in for Shell: records commands, never touches a device."""

    def __init__(self, lines: list[str] | None = None):
        self._lines = lines or []
        self.commands: list[str] = []

    def stream(self, command: str) -> _FakeStream:
        self.commands.append(command)
        return _FakeStream(self._lines)


def _entries(*lines: str):
    return list(Logcat(_FakeShell(list(lines))))


def test_parses_a_threadtime_line():
    entry = _entries(_PLAIN)[0]
    assert (entry.time, entry.pid, entry.tid) == ("08-10 21:32:22.469", 546, 676)
    assert entry.level is Level.E
    assert entry.tag == "WifiScoringParams"
    assert entry.message == "Invalid frequency(-1)"


def test_strips_a_right_padded_tag():
    """threadtime pads tags on the right; the pad is formatting, not the name."""
    assert _entries(_PADDED_TAG)[0].tag == "healthd"


def test_serves_an_empty_tag_as_empty():
    """The device really did log without a tag; inventing a placeholder would lie."""
    entry = _entries(_EMPTY_TAG)[0]
    assert entry.tag == ""
    assert entry.message == "Stack Depot is disabled"


def test_tag_stops_at_the_first_colon_so_the_message_keeps_its_own():
    """Tags may contain spaces and messages may contain colons; the split is the first ': '."""
    entry = _entries(_COLONS)[0]
    assert entry.tag == "pci 0000"
    assert entry.message == "00:01.1: legacy IDE quirk"


def test_raw_holds_the_line_the_device_sent():
    assert _entries(_PLAIN)[0].raw == _PLAIN


def test_level_orders_by_severity():
    assert Level.E > Level.W > Level.I > Level.D > Level.V


def test_buffer_markers_are_not_records():
    assert _entries(_MARKER, _PLAIN, _MARKER) == _entries(_PLAIN)


def test_an_unrecognised_line_is_skipped_and_logged(caplog):
    """A hostile or malformed line must not end the stream -- any app can write one."""
    assert _entries("this is not a logcat line") == []
    assert "unrecognised logcat line" in caplog.text


def test_an_unknown_level_letter_is_skipped_and_logged(caplog):
    assert _entries("08-10 21:32:22.469   546   676 Q SomeTag: message") == []
    assert "unrecognised logcat line" in caplog.text


def test_a_bad_line_does_not_stop_good_lines_from_arriving():
    """The whole point of not raising: one forged line must not take down the tail."""
    assert _entries(_PLAIN, "garbage", _PLAIN) == _entries(_PLAIN, _PLAIN)


def test_default_command_starts_at_the_live_tail():
    """logcat's own default replays the whole ring buffer -- over 20k lines on an
    idle emulator -- which would make "read until a line matches" match something
    logged hours ago. This test is what stops that default creeping back."""
    shell = _FakeShell()
    list(Logcat(shell))
    assert shell.commands == ["logcat -v threadtime -T 1"]


def test_a_deeper_tail_still_follows():
    shell = _FakeShell()
    list(Logcat(shell, tail=100))
    assert shell.commands == ["logcat -v threadtime -T 100"]


def test_no_tail_reads_the_whole_buffer_and_keeps_following():
    shell = _FakeShell()
    list(Logcat(shell, tail=None))
    assert shell.commands == ["logcat -v threadtime"]


def test_not_following_dumps_and_stops():
    """-t implies -d, so tail maps onto whichever flag matches follow."""
    shell = _FakeShell()
    list(Logcat(shell, tail=100, follow=False))
    assert shell.commands == ["logcat -v threadtime -t 100"]


def test_not_following_without_a_tail_dumps_the_whole_buffer():
    shell = _FakeShell()
    list(Logcat(shell, tail=None, follow=False))
    assert shell.commands == ["logcat -v threadtime -d"]


def test_tags_filter_to_the_named_levels_and_silence_everything_else():
    shell = _FakeShell()
    list(Logcat(shell, tags={"ActivityManager": Level.W, "art": Level.E}))
    assert shell.commands == [
        "logcat -v threadtime -T 1 ActivityManager:W art:E *:S"
    ]


def test_a_tail_below_one_is_refused():
    """logcat clamps -T 0 to 1 and warns on stderr while still exiting 0, so the
    warning would be swallowed. Refusing is the only loud option."""
    with pytest.raises(ValueError):
        Logcat(_FakeShell(), tail=0)


def test_iterating_twice_starts_a_fresh_logcat():
    """A Logcat is a reusable spec, unlike the single-use Stream underneath it."""
    shell = _FakeShell([_PLAIN])
    spec = Logcat(shell)
    assert list(spec) == list(spec)
    assert len(shell.commands) == 2


class _BlockingStream:
    """A stream that never yields a line on its own; only close() ends it."""

    def __init__(self):
        self._closed = threading.Event()

    def __enter__(self) -> "_BlockingStream":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._closed.set()

    def __iter__(self):
        self._closed.wait()
        return iter(())


class _BlockingShell:
    """Stands in for a Shell whose stream blocks forever, like a live tail with no traffic."""

    def __init__(self):
        self.commands: list[str] = []

    def stream(self, command: str) -> _BlockingStream:
        self.commands.append(command)
        return _BlockingStream()


def test_follow_for_stops_a_stream_blocked_waiting_for_a_line_that_never_comes():
    """The whole point of follow_for: the timeout must end the read, not just decorate it."""
    with Logcat(_BlockingShell()).follow_for(0.05) as records:
        assert list(records) == []


def test_follow_for_refuses_a_non_positive_timeout():
    with pytest.raises(ValueError):
        with Logcat(_FakeShell()).follow_for(0):
            pass


@pytest.mark.emulator
def test_dump_against_real_device_is_finite(device):
    """follow=False must end on its own, and -t must bound what comes back."""
    entries = list(device.logcat(tail=5, follow=False))
    assert 0 < len(entries) <= 5


@pytest.mark.emulator
def test_every_line_of_a_large_dump_parses(device):
    """The regex must cover what the device really emits, not a sample of it.

    Any line matching neither a record nor a marker raises LogcatParseError out
    of the iterator, so reaching the assertion at all is the coverage claim.
    """
    entries = list(device.logcat(tail=2000, follow=False))
    assert len(entries) > 100


@pytest.mark.emulator
def test_yields_an_entry_logged_after_iteration_started(device):
    """Proves live-tail delivery: a record written *after* iteration began arrives.

    The marker is re-emitted on a timer rather than logged once, so the test
    does not depend on the emulator being chatty enough to unblock the read.
    """
    marker = f"gunkata_{uuid.uuid4().hex[:8]}"
    shell = device.shell()
    stop = threading.Event()

    def emit() -> None:
        while not stop.wait(1.0):
            shell(f"log -t {marker} probe")

    emitter = threading.Thread(target=emit, daemon=True)
    emitter.start()
    found = False
    try:
        deadline = time.monotonic() + 60
        for entry in device.logcat():
            if entry.tag == marker:
                found = True
                break
            if time.monotonic() > deadline:
                break
    finally:
        stop.set()
        emitter.join(timeout=5)
    assert found, "a record logged after iteration started never arrived"


@pytest.mark.emulator
def test_breaking_out_reaps_the_remote_logcat(device):
    """Killing the local adb process must reap logcat on the device too."""
    shell = device.shell()
    before = len(shell.pidof("logcat"))
    for _ in device.logcat(tail=50):
        break
    for _ in range(20):
        if len(shell.pidof("logcat")) <= before:
            break
        time.sleep(0.25)
    assert len(shell.pidof("logcat")) <= before


@pytest.mark.emulator
def test_a_logcat_that_fails_on_its_own_is_loud(device, monkeypatch):
    """A non-zero exit must survive the su wrapping and reach the caller."""
    spec = device.logcat()
    monkeypatch.setattr(spec, "command", lambda: "logcat -d -b nosuchbuffer")
    with pytest.raises(ShellError) as raised:
        list(spec)
    assert raised.value.rc != 0
