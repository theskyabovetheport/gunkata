import subprocess

import pytest
from typer.testing import CliRunner

from gunkata.adb import AdbDeviceEntry
from gunkata.cli import device  # noqa: F401 -- imported for its command-registration side effect
from gunkata.cli.app import app
from gunkata.common.paths import Paths
from gunkata.device import DeviceSettingsStore


class _FakeAdb:
    """Same shape as the fake in tests/inventory/test_roster.py: a class-level
    device list plus per-serial shell responses."""

    _entries: list[AdbDeviceEntry] = []
    _shell_responses: dict[tuple[str, str], subprocess.CompletedProcess] = {}

    def __init__(self, serial: str | None = None):
        """None mirrors real Adb's auto-detect: the fixture's sole entry."""
        self.serial = serial or _FakeAdb._entries[0].serial

    def __call__(self, args, **kwargs):
        command = args[-1] if args and args[0] == "shell" else ""
        key = (self.serial, command)
        if key not in type(self)._shell_responses:
            raise AssertionError(f"unexpected command for {self.serial}: {command!r}")
        return type(self)._shell_responses[key]

    @staticmethod
    def list_devices():
        return _FakeAdb._entries


class _FakeAdbFactory:
    """Stands in for gunkata.adb.AdbFactory, building _FakeAdb instead of Adb."""

    def __call__(self, serial: str | None = None) -> _FakeAdb:
        return _FakeAdb(serial)

    def list_devices(self):
        return _FakeAdb.list_devices()


def _cp(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    """Every test gets its own GUNKATA_ROOT so none share state."""
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))


@pytest.fixture
def fake_adb(monkeypatch):
    _FakeAdb._entries = [AdbDeviceEntry("emulator-5554", "device")]
    _FakeAdb._shell_responses = {
        ("emulator-5554", "getprop"): _cp("[ro.product.model]: [Pixel 4]\n")
    }
    monkeypatch.setattr(device, "AdbFactory", _FakeAdbFactory)
    monkeypatch.setattr(device, "Adb", _FakeAdb)
    return _FakeAdb


def test_devices_renders_the_default_column_alongside_the_fixed_ones(fake_adb):
    result = CliRunner().invoke(app, ["devices"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].split() == ["SERIAL", "NAME", "TAGS", "STATE", "MODEL"]
    assert lines[1].split() == ["emulator-5554", "-", "-", "device", "Pixel", "4"]


def test_devices_reports_no_devices_without_erroring(monkeypatch):
    _FakeAdb._entries = []
    _FakeAdb._shell_responses = {}
    monkeypatch.setattr(device, "AdbFactory", _FakeAdbFactory)
    result = CliRunner().invoke(app, ["devices"])
    assert result.exit_code == 0
    assert "no adb devices" in result.output


def test_devices_select_prints_only_the_chosen_serial_on_stdout(fake_adb):
    """The numbered table and prompt must land on stderr, not mix into stdout."""
    result = CliRunner().invoke(app, ["devices", "--select"], input="1\n")
    assert result.exit_code == 0
    assert result.stdout == "emulator-5554\n"
    assert "MODEL" in result.stderr
    assert "select device number" in result.stderr


def test_devices_select_exits_on_an_out_of_range_number(fake_adb):
    result = CliRunner().invoke(app, ["devices", "--select"], input="2\n")
    assert result.exit_code == 1


def test_devices_select_exits_on_non_numeric_input(fake_adb):
    result = CliRunner().invoke(app, ["devices", "--select"], input="nope\n")
    assert result.exit_code == 2


def test_devices_select_exits_with_no_devices(monkeypatch):
    _FakeAdb._entries = []
    _FakeAdb._shell_responses = {}
    monkeypatch.setattr(device, "AdbFactory", _FakeAdbFactory)
    result = CliRunner().invoke(app, ["devices", "--select"])
    assert result.exit_code == 1


def test_devices_rejects_edit_and_select_together(fake_adb):
    result = CliRunner().invoke(app, ["devices", "--edit", "--select"])
    assert result.exit_code == 2
    assert "at most one" in result.output


def test_name_persists_and_a_later_listing_reflects_it(fake_adb):
    """No serial argument: the target device resolves via the sole connected
    device, same as every other command."""
    result = CliRunner().invoke(app, ["device", "name", "my phone"])
    assert result.exit_code == 0

    listing = CliRunner().invoke(app, ["devices"])
    assert "my phone" in listing.output


def test_tag_add_and_remove_round_trip_through_devices(fake_adb):
    CliRunner().invoke(app, ["device", "tag", "add", "rooted"])
    with_tag = CliRunner().invoke(app, ["devices"])
    assert "rooted" in with_tag.output

    CliRunner().invoke(app, ["device", "tag", "remove", "rooted"])
    without_tag = CliRunner().invoke(app, ["devices"])
    assert "rooted" not in without_tag.output


def test_malformed_list_config_errors_loudly(fake_adb, tmp_path):
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir()
    (devices_dir / "list-config.yaml").write_text("not: [valid")
    result = CliRunner().invoke(app, ["devices"])
    assert result.exit_code == 1


def test_note_dash_m_appends_directly_without_touching_an_editor(fake_adb, tmp_path):
    result = CliRunner().invoke(app, ["device", "note", "-m", "  hello  "])
    assert result.exit_code == 0
    note_path = tmp_path / "devices" / "emulator-5554" / "note"
    assert "hello" in note_path.read_text()


def test_note_without_dash_m_composes_via_the_editor(fake_adb, monkeypatch, tmp_path):
    monkeypatch.setattr(device, "launch", lambda editor, **kw: b"composed note\n")
    result = CliRunner().invoke(app, ["device", "note", "--editor", "fake-editor"])
    assert result.exit_code == 0
    note_path = tmp_path / "devices" / "emulator-5554" / "note"
    assert "composed note" in note_path.read_text()


def test_note_dash_m_with_only_whitespace_is_rejected(fake_adb, tmp_path):
    result = CliRunner().invoke(app, ["device", "note", "-m", "   "])
    assert result.exit_code == 1
    assert not (tmp_path / "devices" / "emulator-5554" / "note").exists()


def test_note_editor_producing_only_whitespace_is_rejected(fake_adb, monkeypatch, tmp_path):
    monkeypatch.setattr(device, "launch", lambda editor, **kw: b"   \n")
    result = CliRunner().invoke(app, ["device", "note", "--editor", "fake-editor"])
    assert result.exit_code == 1
    assert not (tmp_path / "devices" / "emulator-5554" / "note").exists()


def test_note_without_dash_m_and_no_editor_configured_errors_loudly(fake_adb, monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    result = CliRunner().invoke(app, ["device", "note"])
    assert result.exit_code == 1
    assert "editor" in result.output


def test_env_prints_persisted_settings_as_export_lines(fake_adb, tmp_path):
    DeviceSettingsStore(Paths(root=tmp_path)).set(
        "emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root"
    )
    result = CliRunner().invoke(app, ["device", "env"])
    assert result.exit_code == 0
    assert result.output == "export GUNKATA_SHELL_DEFAULT_USER=root\n"


def test_env_skips_a_key_already_set_in_the_shell(fake_adb, monkeypatch, tmp_path):
    """A device's own setting must never override an explicit shell export."""
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "shell")
    DeviceSettingsStore(Paths(root=tmp_path)).set(
        "emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root"
    )
    result = CliRunner().invoke(app, ["device", "env"])
    assert result.exit_code == 0
    assert result.output == ""


def test_env_quotes_a_value_containing_whitespace(fake_adb, tmp_path):
    DeviceSettingsStore(Paths(root=tmp_path)).set(
        "emulator-5554", "GUNKATA_SU_COMMAND", "su -c cmd"
    )
    result = CliRunner().invoke(app, ["device", "env"])
    assert result.output == "export GUNKATA_SU_COMMAND='su -c cmd'\n"


def test_env_errors_loudly_on_a_malformed_settings_file(fake_adb, tmp_path):
    settings_path = tmp_path / "devices" / "emulator-5554" / "settings"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text("not a valid line\n")
    result = CliRunner().invoke(app, ["device", "env"])
    assert result.exit_code == 1


def test_env_edit_round_trips_a_changed_buffer(fake_adb, monkeypatch, tmp_path):
    """Deleting a line unsets that key; a changed value re-sets it; a new
    line sets a key that wasn't there before -- one edit, no set/unset/get."""
    store = DeviceSettingsStore(Paths(root=tmp_path))
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    store.set("emulator-5554", "GUNKATA_FRIDA_PORT", "1234")
    monkeypatch.setattr(
        device,
        "launch",
        lambda editor, **kw: b"export GUNKATA_SHELL_DEFAULT_USER=shell\n"
        b"export GUNKATA_SU_COMMAND=su\n",
    )
    monkeypatch.setattr(device, "resolve_editor", lambda: "fake-editor")
    result = CliRunner().invoke(app, ["device", "env", "--edit"])
    assert result.exit_code == 0
    assert store.load("emulator-5554") == {
        "GUNKATA_SHELL_DEFAULT_USER": "shell",
        "GUNKATA_SU_COMMAND": "su",
    }


def test_env_edit_seeds_the_editor_with_a_key_shadowed_by_the_shell(
    fake_adb, monkeypatch, tmp_path
):
    """Editing must see every persisted key, even one the shell currently
    shadows -- the filtered view `env` prints would silently drop it."""
    monkeypatch.setenv("GUNKATA_SHELL_DEFAULT_USER", "shell")
    DeviceSettingsStore(Paths(root=tmp_path)).set(
        "emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root"
    )
    seeded = {}

    def _fake_launch(editor, initial=b"", **kw):
        seeded["initial"] = initial
        return initial

    monkeypatch.setattr(device, "launch", _fake_launch)
    monkeypatch.setattr(device, "resolve_editor", lambda: "fake-editor")
    result = CliRunner().invoke(app, ["device", "env", "--edit"])
    assert result.exit_code == 0
    assert seeded["initial"] == b"export GUNKATA_SHELL_DEFAULT_USER=root\n"


def test_env_edit_rejects_a_malformed_buffer_without_writing(fake_adb, monkeypatch, tmp_path):
    store = DeviceSettingsStore(Paths(root=tmp_path))
    store.set("emulator-5554", "GUNKATA_SHELL_DEFAULT_USER", "root")
    monkeypatch.setattr(device, "launch", lambda editor, **kw: b"not export syntax\n")
    monkeypatch.setattr(device, "resolve_editor", lambda: "fake-editor")
    result = CliRunner().invoke(app, ["device", "env", "--edit"])
    assert result.exit_code == 1
    assert store.load("emulator-5554") == {"GUNKATA_SHELL_DEFAULT_USER": "root"}


def test_env_edit_with_no_editor_configured_errors_loudly(fake_adb, monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    result = CliRunner().invoke(app, ["device", "env", "--edit"])
    assert result.exit_code == 1
    assert "editor" in result.output


def test_devices_edit_seeds_the_editor_with_the_built_in_default(monkeypatch):
    """No list-config.yaml exists yet, so the editable buffer is the same
    default `load` would have parsed."""
    from gunkata.inventory.list_config import DEFAULT_LIST_CONFIG_YAML

    seeded = {}

    def _fake_launch(editor, initial=b"", **kw):
        seeded["initial"] = initial
        return initial

    monkeypatch.setattr(device, "launch", _fake_launch)
    monkeypatch.setattr(device, "resolve_editor", lambda: "fake-editor")
    result = CliRunner().invoke(app, ["devices", "--edit"])
    assert result.exit_code == 0
    assert seeded["initial"] == DEFAULT_LIST_CONFIG_YAML.encode()


def test_devices_edit_writes_back_the_edited_yaml(fake_adb, monkeypatch, tmp_path):
    new_yaml = b"columns:\n  - name: SERIAL_NO\n    getprop: ro.serialno\n"
    monkeypatch.setattr(device, "launch", lambda editor, **kw: new_yaml)
    monkeypatch.setattr(device, "resolve_editor", lambda: "fake-editor")
    result = CliRunner().invoke(app, ["devices", "--edit"])
    assert result.exit_code == 0
    assert (tmp_path / "devices" / "list-config.yaml").read_bytes() == new_yaml

    listing = CliRunner().invoke(app, ["devices"])
    assert "SERIAL_NO" in listing.output


def test_devices_edit_rejects_invalid_yaml_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(device, "launch", lambda editor, **kw: b"not: [valid")
    monkeypatch.setattr(device, "resolve_editor", lambda: "fake-editor")
    result = CliRunner().invoke(app, ["devices", "--edit"])
    assert result.exit_code == 1
    assert not (tmp_path / "devices" / "list-config.yaml").exists()


def test_devices_edit_with_no_editor_configured_errors_loudly(monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    result = CliRunner().invoke(app, ["devices", "--edit"])
    assert result.exit_code == 1
    assert "editor" in result.output
