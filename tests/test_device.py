import subprocess

import pytest

from gunkata.device import Device, DeviceState


class _SpyAdb:
    """Records the args it was called with; returns a canned CompletedProcess."""

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        return subprocess.CompletedProcess(
            args=args, returncode=self._returncode, stdout=self._stdout, stderr=""
        )


def test_get_state_strips_and_returns_adb_output():
    adb = _SpyAdb(stdout="device\n")
    assert Device(adb).get_state() == "device"
    assert adb.calls == [["get-state"]]


def test_wait_for_state_sends_the_state_value():
    adb = _SpyAdb()
    Device(adb).wait_for_state(DeviceState.device)
    assert adb.calls == [["wait-for-device"]]


def test_shell_returns_a_shell_bound_to_the_given_user_and_the_device_su_binary():
    shell = Device(_SpyAdb(), su_binary="custom-su").shell(user="root")
    assert shell.user == "root"
    assert shell.su_binary == "custom-su"


@pytest.mark.emulator
def test_get_state_against_real_device(device: Device):
    """A live, booted emulator must report the 'device' state."""
    assert device.get_state() == "device"


@pytest.mark.emulator
def test_wait_for_state_against_real_device_returns_immediately(device: Device):
    """wait-for-device on an already-booted device must return without hanging."""
    device.wait_for_state(DeviceState.device)
