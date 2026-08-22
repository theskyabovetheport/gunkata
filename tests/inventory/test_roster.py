import subprocess
from typing import ClassVar

from gunkata.adb import AdbDeviceEntry
from gunkata.common.paths import Paths
from gunkata.inventory.info import DeviceInfoStore
from gunkata.inventory.list_config import ListConfig
from gunkata.inventory.roster import DeviceRoster


class _FakeAdb:
    """Stands in for gunkata.adb.Adb: a class-level device list plus
    per-serial shell responses, so each device can behave differently."""

    _entries: ClassVar[list[AdbDeviceEntry]] = [AdbDeviceEntry("emulator-5554", "device")]
    _shell_responses: ClassVar[dict[tuple[str, str], subprocess.CompletedProcess]] = {}
    getprop_calls: ClassVar[list[str]] = []

    def __init__(self, serial: str):
        self.serial = serial

    def __call__(self, args, **kwargs):
        assert kwargs.get("stdin") == subprocess.DEVNULL
        command = args[-1] if args and args[0] == "shell" else ""
        if command == "getprop":
            type(self).getprop_calls.append(self.serial)
        key = (self.serial, command)
        if key not in type(self)._shell_responses:
            raise AssertionError(f"unexpected command for {self.serial}: {command!r}")
        return type(self)._shell_responses[key]

    @staticmethod
    def list_devices():
        return _FakeAdb._entries


class _FakeAdbFactory:
    """Stands in for gunkata.adb.AdbFactory, building _FakeAdb instead of Adb."""

    def __call__(self, serial: str) -> _FakeAdb:
        return _FakeAdb(serial)

    def list_devices(self):
        return _FakeAdb.list_devices()


def _cp(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _configure(entries, shell_responses):
    _FakeAdb._entries = entries
    _FakeAdb._shell_responses = shell_responses
    _FakeAdb.getprop_calls = []


def _roster(tmp_path, config_body: str) -> DeviceRoster:
    list_config = ListConfig.parse(config_body)
    return DeviceRoster(
        list_config, DeviceInfoStore(Paths(root=tmp_path)), _FakeAdbFactory()
    )


_ONE_GETPROP_COLUMN = "columns:\n  - name: MODEL\n    getprop: ro.product.model\n"
_TWO_GETPROP_COLUMNS = (
    "columns:\n"
    "  - name: MODEL\n    getprop: ro.product.model\n"
    "  - name: SDK\n    getprop: ro.build.version.sdk\n"
)


def test_header_lists_fixed_columns_then_configured_ones(tmp_path):
    roster = _roster(tmp_path, _ONE_GETPROP_COLUMN)
    assert roster.header() == ["SERIAL", "NAME", "TAGS", "STATE", "MODEL"]


def test_row_resolves_a_getprop_column(tmp_path):
    _configure(
        [AdbDeviceEntry("emulator-5554", "device")],
        {
            ("emulator-5554", "getprop"): _cp(
                "[ro.product.model]: [Pixel 4]\n[other]: [x]\n"
            )
        },
    )
    roster = _roster(tmp_path, _ONE_GETPROP_COLUMN)
    assert roster.rows() == [["emulator-5554", "-", "-", "device", "Pixel 4"]]


def test_getprop_dump_happens_once_per_device_regardless_of_column_count(tmp_path):
    """N configured getprop columns must cost one adb round trip, not N."""
    _configure(
        [AdbDeviceEntry("emulator-5554", "device")],
        {
            ("emulator-5554", "getprop"): _cp(
                "[ro.product.model]: [Pixel 4]\n[ro.build.version.sdk]: [34]\n"
            )
        },
    )
    roster = _roster(tmp_path, _TWO_GETPROP_COLUMNS)
    rows = roster.rows()
    assert rows == [["emulator-5554", "-", "-", "device", "Pixel 4", "34"]]
    assert _FakeAdb.getprop_calls == ["emulator-5554"]


def test_shell_column_runs_its_own_command_and_flattens_multiline_output(tmp_path):
    _configure(
        [AdbDeviceEntry("emulator-5554", "device")],
        {("emulator-5554", "uptime"): _cp(" up  4:10,\n0 users\n")},
    )
    roster = _roster(tmp_path, "columns:\n  - name: UPTIME\n    shell: uptime\n")
    assert roster.rows() == [["emulator-5554", "-", "-", "device", "up 4:10, 0 users"]]


def test_shell_column_output_is_truncated_past_forty_characters(tmp_path):
    long_output = "x" * 50
    _configure(
        [AdbDeviceEntry("emulator-5554", "device")],
        {("emulator-5554", "dump"): _cp(long_output)},
    )
    roster = _roster(tmp_path, "columns:\n  - name: DUMP\n    shell: dump\n")
    cell = roster.rows()[0][-1]
    assert len(cell) == 40
    assert cell.endswith("…")


def test_unreachable_device_renders_dash_for_every_configured_column(tmp_path):
    """An offline/unauthorized device must not blow up the whole table."""
    _configure(
        [AdbDeviceEntry("emulator-5554", "offline")],
        {("emulator-5554", "getprop"): _cp("", returncode=1)},
    )
    roster = _roster(tmp_path, _ONE_GETPROP_COLUMN)
    assert roster.rows() == [["emulator-5554", "-", "-", "offline", "-"]]


def test_name_and_tags_come_from_the_info_store_without_touching_the_device(tmp_path):
    _configure(
        [AdbDeviceEntry("emulator-5554", "device")],
        {("emulator-5554", "getprop"): _cp("[ro.product.model]: [Pixel 4]\n")},
    )
    info_store = DeviceInfoStore(Paths(root=tmp_path))
    info_store.set_name("emulator-5554", "my phone")
    info_store.add_tag("emulator-5554", "rooted")
    roster = DeviceRoster(
        ListConfig.parse(_ONE_GETPROP_COLUMN), info_store, _FakeAdbFactory()
    )
    assert roster.rows() == [
        ["emulator-5554", "my phone", "rooted", "device", "Pixel 4"]
    ]


def test_render_numbered_prepends_a_one_based_index_column(tmp_path):
    _configure(
        [
            AdbDeviceEntry("emulator-5554", "device"),
            AdbDeviceEntry("emulator-5556", "device"),
        ],
        {
            ("emulator-5554", "getprop"): _cp("[ro.product.model]: [A]\n"),
            ("emulator-5556", "getprop"): _cp("[ro.product.model]: [B]\n"),
        },
    )
    roster = _roster(tmp_path, _ONE_GETPROP_COLUMN)
    lines = roster.render(numbered=True).splitlines()
    assert lines[0].split()[0] == "#"
    assert lines[1].split()[0] == "1"
    assert lines[2].split()[0] == "2"


def test_render_without_numbered_has_no_index_column(tmp_path):
    _configure(
        [AdbDeviceEntry("emulator-5554", "device")],
        {("emulator-5554", "getprop"): _cp("[ro.product.model]: [A]\n")},
    )
    roster = _roster(tmp_path, _ONE_GETPROP_COLUMN)
    lines = roster.render().splitlines()
    assert lines[0].split()[0] == "SERIAL"
