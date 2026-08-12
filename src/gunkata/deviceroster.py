"""Builds and renders the table `device list`/`device select` show.

Every adb-visible device gets one row: SERIAL, then the locally-known
identity (NAME, TAGS, STATE), then whatever gunkata.deviceconfig.ListConfig
declares. Nothing here is fatal to the whole table -- a device that can't be
reached renders "-" in its own cells, same as the ledger tool's `_field`/
`_cell` convention for an absent or unreachable value.
"""

import re
import subprocess

from gunkata.adb import Adb, AdbDeviceEntry
from gunkata.deviceconfig import Getter, ListConfig
from gunkata.deviceinfo import DeviceInfo, DeviceInfoStore

_CELL_WIDTH = 40
_ADB_TIMEOUT = 10.0
_GETPROP_LINE = re.compile(r"^\[([^\]]+)\]: \[(.*)\]$")


class DeviceRoster:
    """Every currently adb-visible device, resolved against a ListConfig.

    Args:
        list_config: The extra, user-configured columns to append.
        info_store: Where each row's NAME/TAGS cells come from.
    """

    def __init__(self, list_config: ListConfig, info_store: DeviceInfoStore):
        self._list_config = list_config
        self._info_store = info_store

    def header(self) -> list[str]:
        """Returns: SERIAL, NAME, TAGS, STATE, then each configured column's name."""
        return ["SERIAL", "NAME", "TAGS", "STATE", *(c.name for c in self._list_config.columns)]

    def rows(self) -> list[list[str]]:
        """Returns: one row per `adb devices` entry, in adb's own order."""
        return [self._row(entry) for entry in Adb.list_devices()]

    def render(self, numbered: bool = False) -> str:
        """Render header and rows as an aligned table.

        Args:
            numbered: Prepend a 1-based "#" column, for `device select`.

        Returns:
            The table as one string, one line per row including the header;
            no trailing newline.
        """
        header = self.header()
        rows = self.rows()
        if numbered:
            header = ["#", *header]
            rows = [[str(i + 1), *row] for i, row in enumerate(rows)]
        return self._align([header, *rows])

    def _row(self, entry: AdbDeviceEntry) -> list[str]:
        info = self._info_store.load(entry.serial)
        getprops = self._read_getprops(entry.serial) if self._has_getprop_column() else {}
        cells = [entry.serial, *self._identity_cells(info), entry.state]
        for column in self._list_config.columns:
            cells.append(self._resolve(entry.serial, getprops, column.getter))
        return cells

    @staticmethod
    def _identity_cells(info: DeviceInfo) -> list[str]:
        return [info.name or "-", ", ".join(info.tags) or "-"]

    def _has_getprop_column(self) -> bool:
        return any(c.getter.kind == "getprop" for c in self._list_config.columns)

    def _read_getprops(self, serial: str) -> dict[str, str]:
        """One `getprop` dump per device, however many getprop columns are configured.

        Returns:
            Every property the device reported, or {} if it couldn't be
            reached -- a batching optimization, not a source of truth callers
            should treat as exhaustive on failure.
        """
        completed = self._run(serial, ["shell", "getprop"])
        if completed is None or completed.returncode != 0:
            return {}
        props = {}
        for line in completed.stdout.splitlines():
            if m := _GETPROP_LINE.match(line):
                props[m.group(1)] = m.group(2)
        return props

    def _resolve(self, serial: str, getprops: dict[str, str], getter: Getter) -> str:
        if getter.kind == "getprop":
            return getprops.get(getter.arg) or "-"
        completed = self._run(serial, ["shell", getter.arg])
        if completed is None or completed.returncode != 0:
            return "-"
        return self._cell(completed.stdout)

    @staticmethod
    def _run(serial: str, args: list[str]) -> subprocess.CompletedProcess | None:
        """Run one adb shell command, swallowing transport failures as "unreachable".

        Design:
            An offline/unauthorized device makes adb itself fail (non-zero
            exit or an OSError), which must render as "-" in that device's
            cells rather than aborting the whole table. stdin is detached so
            the child adb process can never consume or close the terminal's
            stdin out from under `device select`'s own prompt.
        """
        try:
            return Adb(serial)(
                args,
                capture_output=True,
                text=True,
                timeout=_ADB_TIMEOUT,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _cell(text: str) -> str:
        """Flatten a possibly multi-line value to one bounded-width cell."""
        flat = " ".join(text.split())
        if not flat:
            return "-"
        return flat if len(flat) <= _CELL_WIDTH else flat[: _CELL_WIDTH - 1] + "…"

    @staticmethod
    def _align(table: list[list[str]]) -> str:
        widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
        return "\n".join(
            "  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
            for row in table
        )
