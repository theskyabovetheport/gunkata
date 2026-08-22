import os
import subprocess

import pytest

from gunkata.scrcpy import xephyr as xephyr_mod
from gunkata.scrcpy.xephyr import (
    FrameDisplayError,
    MatchboxUnavailableError,
    NoDisplayError,
    Xephyr,
    XephyrUnavailableError,
)


class _FakeGeometry:
    def __init__(self, width, height):
        self.width = width
        self.height = height


_HOST_SCREEN = (3840, 2160)
"""What the fake host display reports, deliberately unlike the frame's own
size so an assertion can tell which one an argv or a query came from."""

_FRAME_SCREEN = (480, 1040)


class _Connections(list):
    """The connections a test's fake xlib module made, plus a knob for the
    pointer bound the next one enforces."""

    bound: dict
    host: dict


_TESTED_RELEASE = 12101022
"""X.Org 21.1.22: the release the pointer bound was measured correct on."""

_OLD_RELEASE = 12101012
"""X.Org 21.1.12: older than anything tested, so it must warn."""


class _FakeInfo:
    def __init__(self, release):
        self.release_number = release


class _FakeProtocolDisplay:
    """python-xlib puts the server's release number on the protocol display
    under the connection wrapper, which is the only place a server reports it."""

    def __init__(self, release):
        self.info = _FakeInfo(release)


class _FakeProperty:
    def __init__(self, value):
        self.value = value


class _FakePointer:
    def __init__(self, x, y):
        self.root_x = x
        self.root_y = y


class _FakeXlibDisplay:
    """An X connection -- the host's, queried once for its screen size, or the
    frame's own, whose root geometry a test can change to stand for a resize.

    ``pointer_bound`` is how far a warp is allowed to get, standing for the X
    server bounding the pointer to a rectangle smaller than the screen. None
    means unbounded, the healthy case."""

    def __init__(
        self,
        name,
        size=_FRAME_SCREEN,
        pointer_bound=None,
        release=_TESTED_RELEASE,
        wm_name=b"i3",
    ):
        self.name = name
        self.size = size
        self.pointer_bound = pointer_bound
        self.display = _FakeProtocolDisplay(release)
        self.wm_name = wm_name
        self.pointer = _FakePointer(0, 0)
        self.closed = False
        self.geometry_requests = 0
        self.synced = 0

    def screen(self):
        return self

    @property
    def root(self):
        return self

    def get_geometry(self):
        self.geometry_requests += 1
        return _FakeGeometry(*self.size)

    def intern_atom(self, name):
        return name

    def create_resource_object(self, kind, value):
        return self

    def get_full_property(self, atom, kind):
        if atom == "_NET_SUPPORTING_WM_CHECK":
            return _FakeProperty([4242])
        if atom == "_NET_WM_NAME":
            return _FakeProperty(self.wm_name) if self.wm_name else None
        return None

    def query_pointer(self):
        return self.pointer

    def warp_to(self, x, y):
        limit_x, limit_y = self.pointer_bound or self.size
        self.pointer = _FakePointer(min(x, limit_x - 1), min(y, limit_y - 1))

    def sync(self):
        self.synced += 1

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def frame_connection(monkeypatch):
    """Xephyr opens its own X connection to read the frame's size, and no test
    here has a real X server to open. Yields the connections it made, so a test
    can inspect or resize them, and a knob for the pointer bound they
    enforce."""
    made = _Connections()
    bound = {"value": None}
    host = {"release": _TESTED_RELEASE, "wm_name": b"i3", "i3": "i3 version 4.25.1"}

    class _FakeXlibDisplayModule:
        @staticmethod
        def Display(name):
            size = _HOST_SCREEN if name == ":0" else _FRAME_SCREEN
            connection = _FakeXlibDisplay(
                name, size, bound["value"], host["release"], host["wm_name"]
            )
            made.append(connection)
            return connection

    class _Completed:
        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(
        xephyr_mod.subprocess, "run", lambda *a, **k: _Completed(host["i3"])
    )

    class _FakeXtest:
        @staticmethod
        def fake_input(connection, event_type, x=0, y=0):
            connection.warp_to(x, y)

    monkeypatch.setattr(xephyr_mod, "xtest", _FakeXtest)

    monkeypatch.setattr(xephyr_mod, "xlib_display", _FakeXlibDisplayModule)
    made.bound = bound
    made.host = host
    return made


def _frame_connection(made):
    """The connection to the frame itself, not the host queried before it."""
    return next(c for c in made if c.name == ":7")


class _FakeXephyrProcess:
    """A Popen double whose displayfd write and exit are scripted by the test.

    A real Xephyr child inherits write_fd via pass_fds and keeps its own copy
    open; production code closes only its own copy right after Popen returns.
    This fake has no separate child process, so it must not close write_fd
    itself -- writing to it and leaving it open for production code's own
    close to be the one that finally closes it, the same as the real case."""

    def __init__(self, write_fd: int, display_bytes: bytes = b"7\n"):
        os.write(write_fd, display_bytes)
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def kill(self):
        self._returncode = -9

    def wait(self, timeout=None):
        if self._returncode is None:
            raise subprocess.TimeoutExpired(cmd="Xephyr", timeout=timeout)
        return self._returncode


class _FakeFrameClientProcess:
    """A Popen double for anything started *inside* the frame -- matchbox and
    the placeholder's own clients: no displayfd, otherwise identical reap
    behavior to the Xephyr double."""

    def __init__(self):
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def kill(self):
        self._returncode = -9

    def wait(self, timeout=None):
        if self._returncode is None:
            raise subprocess.TimeoutExpired(cmd="frame client", timeout=timeout)
        return self._returncode


def _fake_popen_recording(captured, display_bytes=b"7\n"):
    """A Popen double that dispatches on pass_fds: only Xephyr's own launch
    passes one, so that alone tells the two calls this class makes apart."""
    captured["calls"] = []

    def _popen(argv, pass_fds=(), env=None):
        captured["calls"].append({"argv": argv, "env": env})
        if pass_fds:
            captured["argv"] = argv  # Xephyr's own call, the one pass_fds identifies
            return _FakeXephyrProcess(pass_fds[0], display_bytes)
        return _FakeFrameClientProcess()

    return _popen


def test_display_number_is_read_from_the_server(monkeypatch):
    """The display Xephyr reports over -displayfd is what .display exposes,
    and the argv it was launched with carries every flag this mechanism
    depends on: a title (so a WM rule or this test can find the frame),
    -screen at the host display's own size (see the frame-opens-big guard
    below), and -displayfd (so two concurrent sessions can never race onto one
    display number)."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554")
    with frame.running() as running:
        assert running.display == ":7"
    argv = captured["argv"]
    assert "-title" in argv and "gunkata:emulator-5554" in argv
    assert "-screen" in argv and "3840x2160" in argv
    assert "-displayfd" in argv


def test_the_nested_screen_is_resizeable(monkeypatch):
    """-resizeable is what makes the frame tile. Verified live: with it,
    Xephyr sets no WM_NORMAL_HINTS and i3 tiles the frame, the nested screen
    following each tile size; without it, Xephyr declares min size == max
    size, which i3 floats -- and a WM made to tile it anyway exposes outer
    window past the nested screen that Xephyr never paints."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554").running():
        pass
    assert "-resizeable" in captured["argv"]


def test_matchbox_is_started_inside_the_frames_own_display(monkeypatch):
    """matchbox-window-manager is the fix for scrcpy opening unaligned with
    the frame (verified against a live emulator: with no WM in the nested
    display, an X11 client opens at its own preferred size in a corner
    rather than filling the frame). It must run against the frame's own
    display, never the host's."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554").running():
        pass
    matchbox_calls = [
        c for c in captured["calls"] if c["argv"][0] == "matchbox-window-manager"
    ]
    assert len(matchbox_calls) == 1
    assert matchbox_calls[0]["env"]["DISPLAY"] == ":7"


def test_a_session_without_a_display_is_refused(monkeypatch):
    """No $DISPLAY means no host X server to nest inside -- a Wayland session
    with no XWayland -- and this must be refused before Xephyr is even
    launched, rather than surfacing as Xephyr's own opaque stderr."""
    monkeypatch.delenv("DISPLAY", raising=False)
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554")
    with pytest.raises(NoDisplayError), frame.running():
        pass


def test_a_missing_xephyr_binary_names_the_package(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")

    def _popen(argv, pass_fds=(), env=None):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _popen)
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554")
    with pytest.raises(XephyrUnavailableError) as exc, frame.running():
        pass
    assert "xserver-xephyr" in str(exc.value)


def test_a_missing_matchbox_binary_names_the_package_and_stops_the_frame(monkeypatch):
    """A frame with no in-frame WM would silently reintroduce the unaligned-
    content bug, so a missing matchbox binary must refuse loudly -- and the
    Xephyr process already started for it must not be left orphaned."""
    monkeypatch.setenv("DISPLAY", ":0")
    xephyr_process = {}

    def _popen(argv, pass_fds=(), env=None):
        if pass_fds:
            process = _FakeXephyrProcess(pass_fds[0])
            xephyr_process["process"] = process
            return process
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _popen)
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554")
    with pytest.raises(MatchboxUnavailableError) as exc, frame.running():
        pass
    assert "matchbox-window-manager" in str(exc.value)
    assert xephyr_process["process"].poll() is not None, "the orphaned Xephyr must be reaped"


def test_running_stops_the_frame_and_every_client_it_started(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    processes = []

    original_popen = xephyr_mod.subprocess.Popen

    def _tracking_popen(argv, pass_fds=(), env=None):
        p = original_popen(argv, pass_fds=pass_fds, env=env)
        processes.append(p)
        return p

    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _tracking_popen)
    with Xephyr(
        title="gunkata:emulator-5554", placeholder="waiting for emulator-5554"
    ).running():
        assert all(p.poll() is None for p in processes)
    assert len(processes) == 3, "Xephyr, matchbox, and the placeholder"
    assert all(p.poll() is not None for p in processes)


def test_poll_before_start_raises(monkeypatch):
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554")
    with pytest.raises(RuntimeError):
        frame.poll()


def test_display_before_start_raises(monkeypatch):
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554")
    with pytest.raises(RuntimeError):
        _ = frame.display


def test_no_window_manager_is_ever_consulted(monkeypatch):
    """Geometry is never read or set through a general-purpose WM tool -- the
    frame persisting is the whole mechanism, which is why this is not tied to
    any one host WM. matchbox-window-manager itself is not such a tool: it
    runs *inside* the frame purely to maximize scrcpy's one client, never
    touching the host's own windows, so it is deliberately excluded from
    this list rather than being what this guards against -- as is xmessage,
    which paints the frame's placeholder against that same nested
    display."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(title="gunkata:emulator-5554", placeholder="waiting for emulator-5554").running():
        pass
    argv_text = " ".join(" ".join(c["argv"]) for c in captured["calls"])
    for tool in ("i3-msg", "xdotool", "wmctrl", "xprop", "xwininfo"):
        assert tool not in argv_text


def test_the_placeholder_is_painted_inside_the_frame(monkeypatch):
    """Bare, the gap between one scrcpy and the next is a uniform #000000 --
    measured. xmessage carries the message, and its own -bg is the whole
    background, since xsetroot -solid returns 0 against a Xephyr root and
    leaves it black (also measured). It runs against the frame's own display,
    never the host's."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(
        title="gunkata:emulator-5554", placeholder="waiting for emulator-5554"
    ).running():
        pass
    by_binary = {c["argv"][0]: c for c in captured["calls"]}
    assert by_binary["xmessage"]["env"]["DISPLAY"] == ":7"
    assert "waiting for emulator-5554" in by_binary["xmessage"]["argv"]


def test_the_placeholder_is_started_after_matchbox(monkeypatch):
    """The message has to be a client matchbox already manages, so that it is
    maximized against the nested screen and re-maximized on every resize."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(
        title="gunkata:emulator-5554", placeholder="waiting for emulator-5554"
    ).running():
        pass
    order = [c["argv"][0] for c in captured["calls"]]
    assert order.index("matchbox-window-manager") < order.index("xmessage")


def test_a_missing_placeholder_binary_is_logged_and_skipped(caplog, monkeypatch):
    """The placeholder is cosmetic: it is not needed to mirror a device, so an
    absent binary is a logged skip rather than a refusal -- unlike Xephyr and
    matchbox, which raise. The frame must still come up."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    real_popen = _fake_popen_recording(captured)

    def _popen(argv, pass_fds=(), env=None):
        if argv[0] == "xmessage":
            raise FileNotFoundError(argv[0])
        return real_popen(argv, pass_fds=pass_fds, env=env)

    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _popen)
    with caplog.at_level("INFO", logger="gunkata.scrcpy.xephyr"), Xephyr(
        title="gunkata:emulator-5554", placeholder="waiting for emulator-5554"
    ).running() as frame:
        assert frame.display == ":7"
    assert "xmessage" in caplog.text


def test_screen_size_reports_the_frames_current_size(monkeypatch, frame_connection):
    """The nested screen follows the frame window, so this must be re-read from
    the root window every call. Display.screen()'s own width_in_pixels is
    captured in the connection handshake and would report the size the frame
    opened at forever."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting")
    with frame.running():
        assert frame.screen_size() == (480, 1040)
        _frame_connection(frame_connection).size = (1885, 2108)
        assert frame.screen_size() == (1885, 2108)


def test_screen_size_before_start_raises():
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting")
    with pytest.raises(RuntimeError):
        frame.screen_size()


def test_a_frame_display_that_refuses_a_connection_is_named(monkeypatch):
    """screen_size is load-bearing -- scrcpy is relaunched off it -- so a frame
    whose own display will not answer is a refusal naming it, never a session
    that silently stops noticing resizes."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))

    class _RefusingFrameModule:
        @staticmethod
        def Display(name):
            if name == ":0":
                return _FakeXlibDisplay(name, _HOST_SCREEN)  # host connects fine
            raise OSError("connection refused")

    monkeypatch.setattr(xephyr_mod, "xlib_display", _RefusingFrameModule)
    with (
        pytest.raises(FrameDisplayError) as exc,
        Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running(),
    ):
        pass
    assert ":7" in str(exc.value)


def test_stopping_the_frame_closes_its_x_connection(monkeypatch, frame_connection):
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running():
        assert _frame_connection(frame_connection).closed is False
    assert _frame_connection(frame_connection).closed is True


def test_the_frame_opens_at_the_host_screens_size(monkeypatch):
    """Measured against a live emulator: Xephyr confines the pointer to the
    screen size it opened with, and a RandR resize never widens that box --
    two clicks 500px apart beyond the boundary landed on the same device pixel.
    Opening at the host screen's size, the largest any WM can hand out, is what
    keeps every part of the frame clickable."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running():
        pass
    argv = captured["argv"]
    assert argv[argv.index("-screen") + 1] == "3840x2160"


def test_no_host_display_is_refused_before_anything_starts(monkeypatch):
    """A frame that cannot measure the host has no size to open at, so this
    must refuse rather than guess one."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(
        xephyr_mod.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("nothing may be started without a host display"),
    )
    with (
        pytest.raises(NoDisplayError),
        Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running(),
    ):
        pass


def test_a_pointer_bounded_short_of_the_screen_warns_loudly(caplog, monkeypatch, frame_connection):
    """Measured on another machine: after a resize the X server can keep
    bounding the pointer to a rectangle smaller than the screen, so clicks past
    it land short -- silently, looking like a device or scrcpy fault. No version
    predicts it (the same Xephyr build behaves correctly here), so the bound is
    measured, and the warning must name it and the way out."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame_connection.bound["value"] = (480, 687)
    with caplog.at_level("WARNING", logger="gunkata.scrcpy.xephyr"):
        frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting")
        with frame.running():
            assert frame.check_pointer_reaches_the_screen() is False
    assert "480x687" in caplog.text
    assert "1885x2108" not in caplog.text  # the screen is the frame's, not a guess
    assert "480x1040" in caplog.text
    assert "Restart this gunkata scrcpy session" in caplog.text


def test_a_pointer_that_reaches_the_screen_warns_about_nothing(
    caplog, monkeypatch, frame_connection
):
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with caplog.at_level("WARNING", logger="gunkata.scrcpy.xephyr"):
        frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting")
        with frame.running():
            assert frame.check_pointer_reaches_the_screen() is True
    assert caplog.text == ""


def test_the_pointer_probe_puts_the_pointer_back(monkeypatch, frame_connection):
    """The probe runs while scrcpy is down, but the pointer must still be left
    where the user had it rather than parked in a corner."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame = Xephyr(title="gunkata:emulator-5554", placeholder="waiting")
    with frame.running():
        connection = _frame_connection(frame_connection)
        connection.warp_to(123, 456)
        frame.check_pointer_reaches_the_screen()
        assert (connection.pointer.root_x, connection.pointer.root_y) == (123, 456)


def test_an_old_host_x_server_warns_loudly(caplog, monkeypatch, frame_connection):
    """Asked for explicitly: warn up front, before a resize can strand clicks.
    The claim is an untested combination, not a defect -- the bound went stale on
    X.Org 21.1.12 and not on 21.1.22, two samples that also differ in i3, so
    neither number is a fix point."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame_connection.host["release"] = _OLD_RELEASE
    with (
        caplog.at_level("WARNING", logger="gunkata.scrcpy.xephyr"),
        Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running(),
    ):
        pass
    assert "21.1.12" in caplog.text
    assert "21.1.22" in caplog.text


def test_an_old_i3_warns_loudly(caplog, monkeypatch, frame_connection):
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame_connection.host["i3"] = "i3 version 4.23 (2023-10-29)"
    with (
        caplog.at_level("WARNING", logger="gunkata.scrcpy.xephyr"),
        Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running(),
    ):
        pass
    assert "i3 4.23" in caplog.text
    assert "4.25.1" in caplog.text


def test_an_i3_that_is_not_the_running_wm_is_not_warned_about(
    caplog, monkeypatch, frame_connection
):
    """An i3 installed beside another window manager says nothing about this
    session, so the version it reports must not be warned about -- which is why
    the WM is identified from _NET_SUPPORTING_WM_CHECK, not from PATH."""
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    frame_connection.host["wm_name"] = b"Mutter"
    frame_connection.host["i3"] = "i3 version 4.23 (2023-10-29)"
    with (
        caplog.at_level("WARNING", logger="gunkata.scrcpy.xephyr"),
        Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running(),
    ):
        pass
    assert caplog.text == ""


def test_a_tested_host_warns_about_nothing(caplog, monkeypatch, frame_connection):
    monkeypatch.setenv("DISPLAY", ":0")
    captured = {}
    monkeypatch.setattr(xephyr_mod.subprocess, "Popen", _fake_popen_recording(captured))
    with (
        caplog.at_level("WARNING", logger="gunkata.scrcpy.xephyr"),
        Xephyr(title="gunkata:emulator-5554", placeholder="waiting").running(),
    ):
        pass
    assert caplog.text == ""
