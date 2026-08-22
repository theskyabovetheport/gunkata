import pytest

from gunkata.common.paths import Paths
from gunkata.device import DeviceSettingsError, DeviceSettingsStore


@pytest.fixture
def store(tmp_path) -> DeviceSettingsStore:
    return DeviceSettingsStore(Paths(root=tmp_path))


def test_load_with_no_file_yet_returns_empty(store):
    assert store.load("emulator-5554") == {}


def test_set_persists_and_load_reflects_it(store):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    assert store.load("emulator-5554") == {"GUNKATA_SHELL_DEFAULT_USER": "root"}


def test_set_replaces_a_previous_value_for_the_same_key(store):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "shell")
    assert store.load("emulator-5554")["GUNKATA_SHELL_DEFAULT_USER"] == "shell"


def test_unset_drops_the_key(store):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.unset("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER")
    assert store.load("emulator-5554") == {}


def test_unset_on_an_absent_key_is_a_no_op(store):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.unset("emulator-5554", "NOT_THERE")
    assert store.load("emulator-5554") == {"GUNKATA_SHELL_DEFAULT_USER": "root"}


def test_settings_are_kept_per_serial(store):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.set("emulator-5556", "GUNKATA_SHELL_DEFAULT_USER", "shell")
    assert store.load("emulator-5554")["GUNKATA_SHELL_DEFAULT_USER"] == "root"
    assert store.load("emulator-5556")["GUNKATA_SHELL_DEFAULT_USER"] == "shell"


def test_settings_are_stored_as_key_equals_value_lines(store, tmp_path):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.set("emulator-5554", "GUNKATA_FRIDA_PORT", "1234")
    path = Paths(root=tmp_path).device_settings_path("emulator-5554")
    assert path.read_text() == "GUNKATA_SHELL_DEFAULT_USER=root\nGUNKATA_FRIDA_PORT=1234\n"


def test_load_ignores_blank_lines_and_comments(store, tmp_path):
    path = Paths(root=tmp_path).device_settings_path("emulator-5554")
    path.parent.mkdir(parents=True)
    path.write_text("# a comment\n\nGUNKATA_SHELL_DEFAULT_USER=root\n")
    assert store.load("emulator-5554") == {"GUNKATA_SHELL_DEFAULT_USER": "root"}


def test_environment_returns_the_persisted_assignments(store):
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    assert store.environment("emulator-5554") == {"GUNKATA_SHELL_DEFAULT_USER": "root"}


def test_environment_drops_a_key_the_process_already_has(store, monkeypatch):
    """A value the caller exported outranks the device's stored one.

    An explicit export is a decision made for this shell; a device default
    silently overruling it would make the exported value a lie. The key must
    be absent from the result entirely, not present with the caller's value.
    """
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "shell")
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.set("emulator-5554", "GUNKATA_SU_COMMAND", "su {user} -c '{command}'")
    assert store.environment("emulator-5554") == {
        "GUNKATA_SU_COMMAND": "su {user} -c '{command}'"
    }


def test_environment_with_no_file_yet_returns_empty(store):
    assert store.environment("emulator-5554") == {}


def test_load_raises_on_a_line_that_is_not_key_equals_value(store, tmp_path):
    path = Paths(root=tmp_path).device_settings_path("emulator-5554")
    path.parent.mkdir(parents=True)
    path.write_text("not-key-value\n")
    with pytest.raises(DeviceSettingsError):
        store.load("emulator-5554")
