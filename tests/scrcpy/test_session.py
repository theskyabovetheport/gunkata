from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path

import pytest

from gunkata.scrcpy import session as session_mod
from gunkata.scrcpy.repo import ScrcpyAssetError
from gunkata.scrcpy.session import ScrcpyBootTimeoutError, ScrcpyLaunchError, ScrcpySession
from gunkata.scrcpy.settings import ScrcpySettings

_Result = namedtuple("_Result", ["stdout"])


class _FakeShell:
    """Answers getprop sys.boot_completed from device's own shared queue,
    so each poll round consumes it the same way a fresh Shell would."""

    def __init__(self, device):
        self._device = device

    def sh(self, command):
        values = self._device.boot_completed_sequence
        value = values.pop(0) if len(values) > 1 else values[0]
        return _Result(stdout=value)


class _FakeDevice:
    def __init__(self, serial, boot_completed_sequence):
        self.serial = serial
        self.boot_completed_sequence = list(boot_completed_sequence)
        self.wait_for_state_calls = 0
        self.shell_calls = 0

    def wait_for_state(self, state):
        assert state == "device"
        self.wait_for_state_calls += 1

    def shell(self, user=None):
        self.shell_calls += 1
        return _FakeShell(self)


class _FakeRepo:
    def __init__(self, binary: Path):
        self._binary = binary
        self.resolve_calls = 0

    def resolve(self, version=None):
        self.resolve_calls += 1
        return self._binary


class _FailingRepo:
    def resolve(self, version=None):
        raise ScrcpyAssetError("no archive")


class _FakeScrcpyProcess:
    """A Popen double: exits on its own after running_polls checks, or once
    terminate()/kill() is called -- whichever comes first, exactly like a
    real process asked to stop."""

    def __init__(self, running_polls: int, returncode: int = 0):
        self._remaining = running_polls
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        if self.terminated or self.killed:
            return self.returncode
        if self._remaining > 0:
            self._remaining -= 1
            return None
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


class _FakeFrame:
    """poll() reports closed once at least close_after launches have started,
    a shared counter incremented by the fake Popen -- so the frame's own
    lifetime is expressed in terms of scrcpy launches, not real wall time.

    screen_size() walks sizes the same way _FakeShell walks boot_completed:
    each call consumes one until the last, which then repeats. A single-entry
    list is therefore a frame that never resizes."""

    display = ":7"

    def __init__(self, launches: list[int], close_after: int | None, sizes=None):
        self._launches = launches
        self._close_after = close_after
        self._sizes = list(sizes) if sizes else [(480, 1040)]
        self.pointer_checks = 0

    def poll(self):
        if self._close_after is None:
            return None
        return 0 if self._launches[0] >= self._close_after else None

    def screen_size(self):
        return self._sizes.pop(0) if len(self._sizes) > 1 else self._sizes[0]

    def check_pointer_reaches_the_screen(self):
        self.pointer_checks += 1
        return True


def _fake_xephyr_class(launches: list[int], close_after: int | None, sizes=None):
    instances = []

    class _FakeXephyr:
        def __init__(self, title, placeholder, settings):
            self.title = title
            self.placeholder = placeholder
            self.settings = settings
            self.frame = _FakeFrame(launches, close_after, sizes)
            instances.append(self)

        @contextmanager
        def running(self):
            yield self.frame

    _FakeXephyr.instances = instances
    return _FakeXephyr


def _fast_settings(**overrides):
    return ScrcpySettings(poll_interval_seconds=0.001, **overrides)


def test_a_device_reboot_relaunches_scrcpy_into_the_same_frame(monkeypatch):
    """The whole feature: scrcpy dying (as it does on every device reboot) is
    followed by waiting for the device and relaunching into the one frame
    that was started for the session -- never a second frame."""
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=2))

    processes = [
        _FakeScrcpyProcess(running_polls=0, returncode=1),  # dies (simulated reboot)
        _FakeScrcpyProcess(running_polls=0, returncode=0),  # dies again -> frame closes
    ]

    def _popen(argv, env=None):
        launches[0] += 1
        return processes[launches[0] - 1]

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(device, repo=repo, settings=_fast_settings())
    session.run()

    Xephyr = session_mod.Xephyr
    assert len(Xephyr.instances) == 1, "a reboot must not start a second frame"
    assert launches[0] == 2
    assert device.wait_for_state_calls == 2, "each relaunch awaits the device again"


def test_the_frame_dying_ends_the_session_and_reaps_scrcpy(monkeypatch):
    """Closing the frame ends the session even if scrcpy is still running --
    and scrcpy must be reaped, never left orphaned."""
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=1))

    process = _FakeScrcpyProcess(running_polls=10**6)

    def _popen(argv, env=None):
        launches[0] += 1
        return process

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(device, repo=repo, settings=_fast_settings())
    session.run()

    assert launches[0] == 1
    assert process.terminated is True


def test_the_binary_is_resolved_before_the_frame_starts(monkeypatch):
    """A download or checksum failure must never leave an orphan frame
    on-screen -- resolve() runs first, and Xephyr is never even constructed
    if it raises."""
    launches = [0]
    FakeXephyr = _fake_xephyr_class(launches, close_after=1)
    monkeypatch.setattr(session_mod, "Xephyr", FakeXephyr)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    session = ScrcpySession(device, repo=_FailingRepo(), settings=_fast_settings())
    with pytest.raises(ScrcpyAssetError):
        session.run()
    assert FakeXephyr.instances == []


def test_boot_completed_is_awaited_before_relaunch(monkeypatch):
    """A device that reports boot_completed=0 a few times before flipping to 1
    must be polled, not treated as ready on the first check."""
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=1))

    def _popen(argv, env=None):
        launches[0] += 1
        return _FakeScrcpyProcess(running_polls=0, returncode=0)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["0", "0", "1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(device, repo=repo, settings=_fast_settings())
    session.run()

    assert device.shell_calls == 3


def test_boot_timeout_raises_when_the_device_never_comes_back(monkeypatch):
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=None))
    monkeypatch.setattr(
        session_mod.subprocess, "Popen", lambda argv, env=None: pytest.fail("never launched")
    )

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["0"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    settings = _fast_settings(boot_timeout_seconds=0.01)
    session = ScrcpySession(device, repo=repo, settings=settings)
    with pytest.raises(ScrcpyBootTimeoutError) as exc:
        session.run()
    assert "emulator-5554" in str(exc.value)


def test_repeated_fast_failures_refuse_instead_of_spinning(monkeypatch):
    """scrcpy exiting almost immediately, over and over, must stop the
    session with a named error rather than relaunch forever."""
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=None))

    def _popen(argv, env=None):
        launches[0] += 1
        return _FakeScrcpyProcess(running_polls=0, returncode=1)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    settings = _fast_settings(launch_failure_limit=2, min_uptime_seconds=1000.0)
    session = ScrcpySession(device, repo=repo, settings=settings)
    with pytest.raises(ScrcpyLaunchError) as exc:
        session.run()
    assert launches[0] == 2
    assert "argv=" in str(exc.value)


def test_scrcpy_runs_against_the_frame_display_never_the_host(monkeypatch):
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=1))
    captured = {}

    def _popen(argv, env=None):
        launches[0] += 1
        captured["argv"] = argv
        captured["env"] = env
        return _FakeScrcpyProcess(running_polls=0, returncode=0)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(device, repo=repo, settings=_fast_settings())
    session.run()

    env = captured["env"]
    assert env["DISPLAY"] == ":7"
    assert env["SDL_VIDEODRIVER"] == "x11"
    assert "WAYLAND_DISPLAY" not in env
    assert env["ADB"] == "adb"
    assert env["SCRCPY_SERVER_PATH"] == "/opt/scrcpy/scrcpy-server"


def test_scrcpy_argv_carries_the_serial_and_extra_args(monkeypatch):
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=1))
    captured = {}

    def _popen(argv, env=None):
        launches[0] += 1
        captured["argv"] = argv
        return _FakeScrcpyProcess(running_polls=0, returncode=0)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(
        device, repo=repo, settings=_fast_settings(), extra_args=["--no-audio"]
    )
    session.run()

    assert captured["argv"] == [
        "/opt/scrcpy/scrcpy",
        "-s",
        "emulator-5554",
        "--fullscreen",
        "--no-audio",
    ]


def test_scrcpy_is_never_given_a_window_geometry(monkeypatch):
    """The nested screen follows whatever size the host WM gives the frame,
    so a position or size named at launch would be right only until the
    first resize -- matchbox maximizes scrcpy against the screen's current
    size instead."""
    launches = [0]
    monkeypatch.setattr(session_mod, "Xephyr", _fake_xephyr_class(launches, close_after=1))
    captured = {}

    def _popen(argv, env=None):
        launches[0] += 1
        captured["argv"] = argv
        return _FakeScrcpyProcess(running_polls=0, returncode=0)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(device, repo=repo, settings=_fast_settings())
    session.run()

    argv = captured["argv"]
    assert not [arg for arg in argv if arg.startswith("--window-")]


def test_the_frames_placeholder_names_the_device(monkeypatch):
    """The placeholder is what the frame shows while scrcpy is down, so it has
    to say which device is being waited for -- the session is the only thing
    here that knows the serial."""
    launches = [0]
    FakeXephyr = _fake_xephyr_class(launches, close_after=1)
    monkeypatch.setattr(session_mod, "Xephyr", FakeXephyr)
    def _popen(argv, env=None):
        launches[0] += 1
        return _FakeScrcpyProcess(running_polls=0, returncode=0)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    session = ScrcpySession(
        device, repo=_FakeRepo(Path("/opt/scrcpy/scrcpy")), settings=_fast_settings()
    )
    session.run()

    frame = FakeXephyr.instances[0]
    assert frame.title == "gunkata:emulator-5554"
    assert "emulator-5554" in frame.placeholder


def test_a_frame_resize_relaunches_scrcpy(monkeypatch):
    """Verified on a real device: after the frame is resized, scrcpy keeps
    mapping clicks against the geometry it started with, so they land
    progressively too high, while a freshly launched scrcpy is accurate. A
    size change therefore replaces scrcpy rather than trusting it to re-fit."""
    launches = [0]
    monkeypatch.setattr(
        session_mod,
        "Xephyr",
        _fake_xephyr_class(launches, close_after=2, sizes=[(480, 1040), (480, 700)]),
    )

    def _popen(argv, env=None):
        launches[0] += 1
        # Never exits on its own: the resize has to be what ends it.
        return _FakeScrcpyProcess(running_polls=10**6)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    session = ScrcpySession(device, repo=repo, settings=_fast_settings())
    session.run()

    assert launches[0] == 2, "the resize must have replaced the first scrcpy"


def test_a_resize_relaunch_is_not_counted_as_a_launch_failure(monkeypatch):
    """A resize can land moments after a launch, which the hot-loop guard would
    otherwise read as scrcpy dying instantly. launch_failure_limit=1 with a
    min_uptime nothing can satisfy means any counted failure raises, so a clean
    run proves a resize relaunch is not one."""
    launches = [0]
    monkeypatch.setattr(
        session_mod,
        "Xephyr",
        _fake_xephyr_class(launches, close_after=2, sizes=[(480, 1040), (480, 700)]),
    )

    def _popen(argv, env=None):
        launches[0] += 1
        return _FakeScrcpyProcess(running_polls=10**6)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    repo = _FakeRepo(Path("/opt/scrcpy/scrcpy"))
    settings = _fast_settings(launch_failure_limit=1, min_uptime_seconds=1000.0)
    session = ScrcpySession(device, repo=repo, settings=settings)
    session.run()

    assert launches[0] == 2


def test_a_resize_checks_that_the_pointer_still_reaches_the_screen(monkeypatch):
    """A resize is exactly when an X server can strand the pointer short of the
    new screen, and the moment scrcpy is down -- so the probe cannot reach the
    device, and a stale bound is caught rather than left to look like a scrcpy
    fault."""
    launches = [0]
    FakeXephyr = _fake_xephyr_class(
        launches, close_after=2, sizes=[(480, 1040), (480, 700)]
    )
    monkeypatch.setattr(session_mod, "Xephyr", FakeXephyr)

    def _popen(argv, env=None):
        launches[0] += 1
        return _FakeScrcpyProcess(running_polls=10**6)

    monkeypatch.setattr(session_mod.subprocess, "Popen", _popen)

    device = _FakeDevice("emulator-5554", boot_completed_sequence=["1"])
    session = ScrcpySession(
        device, repo=_FakeRepo(Path("/opt/scrcpy/scrcpy")), settings=_fast_settings()
    )
    session.run()

    assert FakeXephyr.instances[0].frame.pointer_checks == 1
