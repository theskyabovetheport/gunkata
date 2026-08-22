import os
import signal

import pytest
from typer.testing import CliRunner

from gunkata.cli import scrcpy
from gunkata.cli.app import app
from gunkata.common.download import BinaryDownloadError
from gunkata.scrcpy.repo import ScrcpyAssetError, ScrcpyChecksumError, UnsupportedHostError
from gunkata.scrcpy.session import ScrcpyBootTimeoutError, ScrcpyLaunchError
from gunkata.scrcpy.xephyr import MatchboxUnavailableError, NoDisplayError, XephyrUnavailableError

runner = CliRunner()


class _FakeDevice:
    def __init__(self):
        self.serial = "emulator-5554"


def _fake_session_factory(run_side_effect=None, captured=None):
    class _FakeSession:
        def __init__(self, device, repo=None, settings=None, extra_args=None):
            if captured is not None:
                captured["device"] = device
                captured["settings"] = settings
                captured["extra_args"] = extra_args

        def run(self):
            if run_side_effect is not None:
                raise run_side_effect

    return _FakeSession


def test_scrcpy_takes_no_frame_size_options():
    """The frame's size is not the user's to choose: Xephyr confines the pointer
    to the size the frame opened with, so it must open at the host screen's own
    size or parts of it stop being clickable."""
    result = runner.invoke(app, ["scrcpy", "--help"])
    assert result.exit_code == 0
    assert "--frame-width" not in result.output
    assert "--frame-height" not in result.output


def test_scrcpy_constructs_a_session_with_the_device_and_passthrough_args(monkeypatch):
    """The command is presentation only: it builds a Device and a
    ScrcpySession and runs it, forwarding unrecognized argv verbatim -- this
    is the construction/wiring smoke test the Definition of Done asks for."""
    captured = {}
    monkeypatch.setattr(scrcpy, "Device", lambda: _FakeDevice())
    monkeypatch.setattr(scrcpy, "ScrcpySession", _fake_session_factory(captured=captured))
    result = runner.invoke(app, ["scrcpy", "--no-audio", "-Sfoo"])
    assert result.exit_code == 0
    assert captured["extra_args"] == ["--no-audio", "-Sfoo"]
    assert captured["device"].serial == "emulator-5554"


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (UnsupportedHostError, "no scrcpy release build"),
        (ScrcpyAssetError, "no scrcpy-linux-x86_64-v4.1.tar.gz in scrcpy repo"),
        (BinaryDownloadError, "failed to download"),
        (ScrcpyChecksumError, "sha256"),
        (NoDisplayError, "no $DISPLAY"),
        (XephyrUnavailableError, "is not on PATH"),
        (MatchboxUnavailableError, "is not on PATH"),
        (ScrcpyBootTimeoutError, "did not report sys.boot_completed"),
        (ScrcpyLaunchError, "exited with rc="),
    ],
)
def test_scrcpy_reports_a_session_failure_without_a_traceback(monkeypatch, error, message):
    """Every failure a session can raise is a user-fixable condition, not a
    crash -- each is caught and echoed to stderr with exit code 1."""
    monkeypatch.setattr(scrcpy, "Device", lambda: _FakeDevice())
    monkeypatch.setattr(
        scrcpy, "ScrcpySession", _fake_session_factory(run_side_effect=error(message))
    )
    result = runner.invoke(app, ["scrcpy"])
    assert result.exit_code == 1
    assert message in result.output


def test_scrcpy_maps_a_keyboard_interrupt_to_exit_130(monkeypatch):
    monkeypatch.setattr(scrcpy, "Device", lambda: _FakeDevice())
    monkeypatch.setattr(
        scrcpy, "ScrcpySession", _fake_session_factory(run_side_effect=KeyboardInterrupt())
    )
    result = runner.invoke(app, ["scrcpy"])
    assert result.exit_code == 130


def test_scrcpy_treats_sigterm_the_same_as_a_keyboard_interrupt(monkeypatch):
    """SIGTERM (a plain `kill`) has no default translation into an exception
    the way SIGINT's default handler does -- unhandled, it would end this
    process immediately mid-session, orphaning Xephyr/matchbox/scrcpy. It
    must map to the same exit code as Ctrl-C instead."""

    class _SelfTerminatingSession:
        def __init__(self, device, repo=None, settings=None, extra_args=None):
            pass

        def run(self):
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(scrcpy, "Device", lambda: _FakeDevice())
    monkeypatch.setattr(scrcpy, "ScrcpySession", _SelfTerminatingSession)
    result = runner.invoke(app, ["scrcpy"])
    assert result.exit_code == 130


def test_scrcpy_restores_the_previous_sigterm_handler_after_running(monkeypatch):
    """The handler installed for the session's own lifetime must not leak
    into whatever ran this process -- a later unrelated SIGTERM elsewhere in
    the same process must not be caught by a stale handler from a session
    that already ended."""
    monkeypatch.setattr(scrcpy, "Device", lambda: _FakeDevice())
    monkeypatch.setattr(scrcpy, "ScrcpySession", _fake_session_factory())
    before = signal.getsignal(signal.SIGTERM)
    runner.invoke(app, ["scrcpy"])
    assert signal.getsignal(signal.SIGTERM) is before
