import subprocess

import pytest

from gunkata.adb import Adb, AdbError


def _fake_devices_output(stdout: str):
    return lambda *args, **kwargs: subprocess.CompletedProcess(
        args=args, returncode=0, stdout=stdout, stderr=""
    )


def test_no_device_raises(monkeypatch):
    """No attached device must raise AdbError, not silently produce an empty serial."""
    monkeypatch.setattr(
        subprocess, "run", _fake_devices_output("List of devices attached\n\n")
    )
    with pytest.raises(AdbError, match="no adb device connected"):
        Adb()


def test_one_device_returns_its_serial(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_devices_output("List of devices attached\nemulator-5554\tdevice\n"),
    )
    assert Adb().serial == "emulator-5554"


def test_multiple_devices_raises(monkeypatch):
    """Ambiguous auto-detect must refuse rather than silently picking one serial."""
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_devices_output(
            "List of devices attached\n"
            "emulator-5554\tdevice\n"
            "emulator-5556\tdevice\n"
        ),
    )
    with pytest.raises(AdbError, match="multiple adb devices connected"):
        Adb()


def test_offline_device_is_excluded(monkeypatch):
    """A device in a non-'device' state (offline/unauthorized) must not count."""
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_devices_output("List of devices attached\nemulator-5554\toffline\n"),
    )
    with pytest.raises(AdbError, match="no adb device connected"):
        Adb()


def test_explicit_serial_skips_autodetect(monkeypatch):
    """Passing a serial must never shell out to `adb devices`."""
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("must not run adb devices")
    )
    assert Adb("emulator-5554").serial == "emulator-5554"


def test_popen_builds_the_same_device_argv_as_a_blocking_call(monkeypatch):
    """Both spawn modes must share one argv site.

    If they diverged, a flag added to the adb invocation would reach only the
    blocking path and the streaming path would silently miss it.
    """
    spawned: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: spawned.append(argv))
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: spawned.append(argv))

    adb = Adb("emulator-5554")
    adb(["shell", "id"])
    adb.popen(["shell", "id"])

    assert spawned == [["adb", "-s", "emulator-5554", "shell", "id"]] * 2


@pytest.mark.emulator
def test_autodetect_against_real_device():
    """Against a single live device, auto-detect must resolve to its real serial."""
    assert Adb().serial
