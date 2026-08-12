"""The device-list column spec: extra columns `device list`/`device select` show.

Ledger-style (see the `ledger` device-tracking tool's `props.yaml`): each
column is named and read via a getter, parsed from one YAML file rather than
hand-wired into the table. It differs from ledger in one place -- ledger
dropped an arbitrary `shell:` getter because a fleet spec runs on *someone
else's* device; gunkata's list-config.yaml only ever runs against devices its
own operator's adb can already reach, so `shell:` stays as the flexibility
valve, and there is no `builtin:` kind at all. Local device identity (name,
tags, adb state) isn't something a shell command or a device property could
produce anyway, so `device list`/`device select` show it as fixed columns
ahead of anything this file declares -- see gunkata.device_roster.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = ("getprop", "shell")

# There is no built-in default *file* -- see DEFAULT_LIST_CONFIG_YAML below --
# but there is a default in-memory config, unlike ledger's spec: this is a
# single-operator tool, not a fleet several people opt into, so a useful
# column out of the box costs nothing nobody already agreed to.
DEFAULT_LIST_CONFIG_YAML = """\
columns:
  - name: MODEL
    getprop: ro.product.model
"""


class ListConfigError(ValueError):
    """Raised when a list-config.yaml document is malformed."""


@dataclass(frozen=True)
class Getter:
    """How a column's value is read from a device.

    Attributes:
        kind: "getprop" or "shell".
        arg: A getprop key, or a shell command run via `adb shell`.
    """

    kind: str
    arg: str


@dataclass(frozen=True)
class Column:
    """One configured column: its header text and how to fill it in."""

    name: str
    getter: Getter


@dataclass(frozen=True)
class ListConfig:
    """The parsed list-config.yaml: columns appended after the fixed identity ones."""

    columns: tuple[Column, ...]

    @classmethod
    def parse(cls, body: str) -> "ListConfig":
        """Parse a list-config.yaml document.

        Raises:
            ListConfigError: body isn't valid YAML, has no `columns` list, or
                a column is missing a name or has other than exactly one of
                `getprop`/`shell`.
        """
        try:
            doc = yaml.safe_load(body)
        except yaml.YAMLError as exc:
            raise ListConfigError(f"not valid YAML: {exc}") from exc

        if not isinstance(doc, dict):
            raise ListConfigError("top level must be a mapping with a `columns` key")

        raw_columns = doc.get("columns")
        if not isinstance(raw_columns, list) or not raw_columns:
            raise ListConfigError("`columns` must be a non-empty list")

        columns: list[Column] = []
        for i, entry in enumerate(raw_columns):
            if not isinstance(entry, dict):
                raise ListConfigError(f"columns[{i}] must be a mapping")
            unknown = set(entry) - {"name", *KINDS}
            if unknown:
                raise ListConfigError(f"columns[{i}] has unknown keys: {sorted(unknown)}")

            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ListConfigError(f"columns[{i}] needs a non-empty string `name`")

            sources = [k for k in KINDS if entry.get(k)]
            if len(sources) != 1:
                raise ListConfigError(
                    f"column {name!r} needs exactly one of {'/'.join(KINDS)}, "
                    f"got {sources or 'none'}"
                )
            kind = sources[0]
            arg = str(entry[kind]).strip()
            if not arg:
                raise ListConfigError(f"column {name!r} has an empty {kind}")
            columns.append(Column(name=name, getter=Getter(kind, arg)))

        return cls(columns=tuple(columns))

    @classmethod
    def load(cls, path: Path) -> "ListConfig":
        """Load list-config.yaml, or the built-in default if it doesn't exist yet.

        Raises:
            ListConfigError: the file exists but is malformed.
        """
        body = path.read_text() if path.exists() else DEFAULT_LIST_CONFIG_YAML
        return cls.parse(body)
