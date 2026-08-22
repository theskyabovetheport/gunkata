import importlib
import subprocess

import pytest

from gunkata.adb import Adb
from gunkata.common.paths import Paths
from gunkata.device import Device, DeviceSettingsError, DeviceSettingsStore, DeviceState

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


class _SpyAdb:
    """Records the args it was called with; returns a canned CompletedProcess.

    Honours the text= kwarg the way real Adb does: get_state asks for text and
    reads str, while Shell captures bytes and decodes them itself. A fake that
    answered str to both would let a decode bug through.
    """

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.serial = "fake-serial"
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._returncode = returncode

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        text = bool(kwargs.get("text"))
        return subprocess.CompletedProcess(
            args=args,
            returncode=self._returncode,
            stdout=self._stdout if text else self._stdout.encode(),
            stderr="" if text else b"",
        )


def _device_with(monkeypatch, adb) -> Device:
    """Build a Device whose resolved Adb is exactly adb, bypassing real auto-detect.

    The same seam every CLI command's own Adb reference is patched through
    -- see cli/procmaps.py's tests -- just one level down, since Device now
    owns resolving its own Adb (_resolve_adb) rather than taking one directly.
    """
    monkeypatch.setattr(device_mod, "Adb", lambda serial=None: adb)
    return Device()


def test_get_state_strips_and_returns_adb_output(monkeypatch):
    adb = _SpyAdb(stdout="device\n")
    assert _device_with(monkeypatch, adb).get_state() == "device"
    assert adb.calls == [["get-state"]]


def test_wait_for_state_sends_the_state_value(monkeypatch):
    adb = _SpyAdb()
    _device_with(monkeypatch, adb).wait_for_state(DeviceState.device)
    assert adb.calls == [["wait-for-device"]]


def test_shell_returns_a_shell_bound_to_the_given_user(monkeypatch):
    shell = _device_with(monkeypatch, _SpyAdb()).shell(user="root")
    assert shell.user == "root"


def test_shell_defaults_to_shell_user_by_default(monkeypatch):
    """default_user is "shell" by default, so a bare shell() stays unwrapped."""
    shell = _device_with(monkeypatch, _SpyAdb()).shell()
    assert shell.user == "shell"


def test_shell_defaults_to_the_configured_default_user(monkeypatch):
    """GUNKATA_SHELL_DEFAULT_USER statically decides the shell's default user."""
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "root")
    shell = _device_with(monkeypatch, _SpyAdb()).shell()
    assert shell.user == "root"


def test_shell_wraps_via_su_for_any_explicit_user_other_than_shell(monkeypatch):
    """Naming a user always wraps through su -- there is no separate enabled
    flag left to gate it, and no env var required."""
    adb = _SpyAdb()
    _device_with(monkeypatch, adb).shell(user="operator").sh("id")
    assert adb.calls == [["shell", "su operator sh -c id"]]


def test_shell_bare_default_tolerates_a_command_template_without_a_user_placeholder(
    monkeypatch,
):
    """A fixed-identity wrapper script is a legitimate default_user=root config
    (see test_custom_command_can_reference_only_the_placeholders_it_needs in
    test_shell.py) -- the {user}-placeholder check exempts "root" for exactly
    this reason, bare default or not."""
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "root")
    monkeypatch.setenv("GUNKATA_SU_COMMAND", "/data/local/tmp/wrapper.sh {command}")
    adb = _SpyAdb()
    _device_with(monkeypatch, adb).shell().sh("id")
    assert adb.calls == [["shell", "/data/local/tmp/wrapper.sh id"]]


def test_shell_never_wraps_the_shell_user_even_named_explicitly(monkeypatch):
    """"shell" names adb's own already-unprivileged user, not an su target --
    an explicit request for it must stay unwrapped even with default_user
    configured to "root"."""
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "root")
    adb = _SpyAdb()
    _device_with(monkeypatch, adb).shell(user="shell").sh("id")
    assert adb.calls == [["shell", "id"]]


def _persist(monkeypatch, tmp_path, key: str, value: str) -> None:
    """Store key=value for _SpyAdb's serial under a fresh GUNKATA_ROOT."""
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    DeviceSettingsStore(Paths(root=tmp_path)).set("fake-serial", key, value)


def test_shell_defaults_to_root_when_the_device_persisted_default_user(
    monkeypatch, tmp_path
):
    """A persisted GUNKATA_SHELL_DEFAULT_USER reaches Su without being exported first.

    This is the whole point of `device env --edit`: the value takes effect
    for the device it was stored against, with no `eval "$(gunkata device
    env)"` in between.
    """
    _persist(monkeypatch, tmp_path, "GUNKATA_SHELL_DEFAULT_USER", "root")
    assert _device_with(monkeypatch, _SpyAdb()).shell().user == "root"


def test_an_exported_value_outranks_the_persisted_one(monkeypatch, tmp_path):
    """The environment wins, so a user can override a device's stored setting
    for one shell without editing the settings file."""
    _persist(monkeypatch, tmp_path, "GUNKATA_SHELL_DEFAULT_USER", "root")
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "shell")
    assert _device_with(monkeypatch, _SpyAdb()).shell().user == "shell"


def test_another_devices_settings_do_not_reach_this_one(monkeypatch, tmp_path):
    """Settings are keyed by serial, so a second device's stored su config
    must not leak into the device actually being operated."""
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    DeviceSettingsStore(Paths(root=tmp_path)).set(
        "some-other-serial", "GUNKATA_SHELL_DEFAULT_USER", "root"
    )
    assert _device_with(monkeypatch, _SpyAdb()).shell().user == "shell"


def test_a_malformed_settings_file_raises_rather_than_running_unwrapped(
    monkeypatch, tmp_path
):
    """A settings file that cannot be parsed must stop the command.

    Falling back to the default would silently run as "shell" on a device the
    user configured for root -- a wrong-user command that looks like it worked.
    """
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    settings_path = Paths(root=tmp_path).device_settings_path("fake-serial")
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("this is not an assignment\n")
    with pytest.raises(DeviceSettingsError):
        _device_with(monkeypatch, _SpyAdb())


def test_has_root_true_when_the_su_wrapped_probe_reports_uid_zero(
    monkeypatch, tmp_path
):
    """The probe must go through su as root, not just run `id -u` as whoever.

    Asserting the command line as well as the verdict is what pins that: a
    probe that skipped the wrapping would report the adb shell user's uid and
    answer False on a perfectly rootable device.
    """
    _persist(monkeypatch, tmp_path, "GUNKATA_SHELL_DEFAULT_USER", "root")
    adb = _SpyAdb(stdout="0\n")
    assert _device_with(monkeypatch, adb).has_root()
    assert adb.calls == [["shell", "su root sh -c 'id -u'"]]


def test_has_root_false_when_the_probe_reports_another_uid(monkeypatch, tmp_path):
    """su ran and succeeded but landed somewhere that is not root."""
    _persist(monkeypatch, tmp_path, "GUNKATA_SHELL_DEFAULT_USER", "root")
    assert not _device_with(monkeypatch, _SpyAdb(stdout="2000\n")).has_root()


def test_has_root_false_when_su_refuses(monkeypatch, tmp_path):
    """A device with no su, or one whose manager denied the request, exits
    non-zero. That is the answer being asked for, so it is reported as False
    rather than raised at a caller who asked a yes/no question."""
    _persist(monkeypatch, tmp_path, "GUNKATA_SHELL_DEFAULT_USER", "root")
    assert not _device_with(monkeypatch, _SpyAdb(stdout="", returncode=1)).has_root()


def test_has_root_false_when_default_user_is_shell_for_the_device(monkeypatch):
    """With default_user left at "shell", commands go to the device unwrapped,
    so the honest answer is that this device's configuration does not reach
    root -- and the probe must not silently wrap itself in su to get a
    rosier one."""
    adb = _SpyAdb(stdout="2000\n")
    assert not _device_with(monkeypatch, adb).has_root()
    assert adb.calls == [["shell", "id -u"]]


@pytest.mark.emulator
def test_has_root_against_real_device_configured_for_su(tmp_path, monkeypatch):
    """The emulator's userdebug image grants su, so a device configured to use
    it reports root -- the True branch, against real hardware rather than a fake."""
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    serial = Adb().serial
    DeviceSettingsStore(Paths(root=tmp_path)).set(serial, "GUNKATA_SHELL_DEFAULT_USER", "root")
    assert Device().has_root()


@pytest.mark.emulator
def test_has_root_false_against_real_device_without_su(device: Device):
    """Same hardware, su left disabled: adb's own shell user is not root, so
    the answer flips. Pins that a real True is earned by the su wrapping."""
    assert not device.has_root()


@pytest.mark.emulator
def test_get_state_against_real_device(device: Device):
    """A live, booted emulator must report the 'device' state."""
    assert device.get_state() == "device"


@pytest.mark.emulator
def test_wait_for_state_against_real_device_returns_immediately(device: Device):
    """wait-for-device on an already-booted device must return without hanging."""
    device.wait_for_state(DeviceState.device)
