import subprocess

import pytest
from typer.testing import CliRunner

from gunkata.adb import AdbDeviceEntry
from gunkata.cli import device  # noqa: F401 -- imported for its command-registration side effect
from gunkata.cli.app import app


class _FakeAdb:
    """Same shape as the fake in test_device_roster.py: a class-level device
    list plus per-serial shell responses."""

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


def test_list_renders_the_default_column_alongside_the_fixed_ones(fake_adb):
    result = CliRunner().invoke(app, ["device", "list"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0].split() == ["SERIAL", "NAME", "TAGS", "STATE", "MODEL"]
    assert lines[1].split() == ["emulator-5554", "-", "-", "device", "Pixel", "4"]


def test_list_reports_no_devices_without_erroring(monkeypatch):
    _FakeAdb._entries = []
    _FakeAdb._shell_responses = {}
    monkeypatch.setattr(device, "AdbFactory", _FakeAdbFactory)
    result = CliRunner().invoke(app, ["device", "list"])
    assert result.exit_code == 0
    assert "no adb devices" in result.output


def test_select_prints_only_the_chosen_serial_on_stdout(fake_adb):
    """The numbered table and prompt must land on stderr, not mix into stdout."""
    result = CliRunner().invoke(app, ["device", "select"], input="1\n")
    assert result.exit_code == 0
    assert result.stdout == "emulator-5554\n"
    assert "MODEL" in result.stderr
    assert "select device number" in result.stderr


def test_select_exits_on_an_out_of_range_number(fake_adb):
    result = CliRunner().invoke(app, ["device", "select"], input="2\n")
    assert result.exit_code == 1


def test_select_exits_on_non_numeric_input(fake_adb):
    result = CliRunner().invoke(app, ["device", "select"], input="nope\n")
    assert result.exit_code == 2


def test_select_exits_with_no_devices(monkeypatch):
    _FakeAdb._entries = []
    _FakeAdb._shell_responses = {}
    monkeypatch.setattr(device, "AdbFactory", _FakeAdbFactory)
    result = CliRunner().invoke(app, ["device", "select"])
    assert result.exit_code == 1


def test_name_persists_and_a_later_list_reflects_it(fake_adb):
    """No serial argument: the target device resolves via the sole connected
    device, same as every other command."""
    result = CliRunner().invoke(app, ["device", "name", "my phone"])
    assert result.exit_code == 0

    listing = CliRunner().invoke(app, ["device", "list"])
    assert "my phone" in listing.output


def test_tag_add_and_remove_round_trip_through_list(fake_adb):
    CliRunner().invoke(app, ["device", "tag", "add", "rooted"])
    with_tag = CliRunner().invoke(app, ["device", "list"])
    assert "rooted" in with_tag.output

    CliRunner().invoke(app, ["device", "tag", "remove", "rooted"])
    without_tag = CliRunner().invoke(app, ["device", "list"])
    assert "rooted" not in without_tag.output


def test_malformed_list_config_errors_loudly(fake_adb, tmp_path):
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir()
    (devices_dir / "list-config.yaml").write_text("not: [valid")
    result = CliRunner().invoke(app, ["device", "list"])
    assert result.exit_code == 1


def test_note_dash_m_appends_directly_without_touching_an_editor(fake_adb, tmp_path):
    result = CliRunner().invoke(app, ["device", "note", "-m", "  hello  "])
    assert result.exit_code == 0
    note_path = tmp_path / "devices" / "info" / "emulator-5554-note"
    assert "hello" in note_path.read_text()


def test_note_without_dash_m_composes_via_the_editor(fake_adb, monkeypatch, tmp_path):
    monkeypatch.setattr(device, "launch", lambda editor, **kw: b"composed note\n")
    result = CliRunner().invoke(app, ["device", "note", "--editor", "fake-editor"])
    assert result.exit_code == 0
    note_path = tmp_path / "devices" / "info" / "emulator-5554-note"
    assert "composed note" in note_path.read_text()


def test_note_dash_m_with_only_whitespace_is_rejected(fake_adb, tmp_path):
    result = CliRunner().invoke(app, ["device", "note", "-m", "   "])
    assert result.exit_code == 1
    assert not (tmp_path / "devices" / "info" / "emulator-5554-note").exists()


def test_note_editor_producing_only_whitespace_is_rejected(fake_adb, monkeypatch, tmp_path):
    monkeypatch.setattr(device, "launch", lambda editor, **kw: b"   \n")
    result = CliRunner().invoke(app, ["device", "note", "--editor", "fake-editor"])
    assert result.exit_code == 1
    assert not (tmp_path / "devices" / "info" / "emulator-5554-note").exists()


def test_note_without_dash_m_and_no_editor_configured_errors_loudly(fake_adb, monkeypatch):
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    result = CliRunner().invoke(app, ["device", "note"])
    assert result.exit_code == 1
    assert "editor" in result.output
