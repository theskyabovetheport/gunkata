"""Where gunkata's persistent, non-cache state lives on disk.

The one shared resolver every module that touches a persistent path must go
through, per CLAUDE.md's General Conventions -- a second, local
``Path.home() / ".gunkata"`` somewhere else would drift from this one the
first time GUNKATA_ROOT is overridden.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Paths(BaseSettings):
    """The root directory gunkata's commands persist state under, and its layout.

    Attributes:
        root: The directory everything below lives under.

    Design:
        A bare directory rather than one path per concern, because every
        concern this repo has so far (the device list config, per-device
        state) nests under one root a user points at once. Per-device state
        nests one directory per serial (``devices/<serial>/``) rather than
        flat serial-prefixed filenames, so everything about one device sits
        under one path a caller (or `rm -r`) can address directly.
    """

    model_config = SettingsConfigDict(populate_by_name=True, frozen=True)

    root: Path = Field(
        default_factory=lambda: Path.home() / ".gunkata",
        validation_alias="GUNKATA_ROOT",
    )

    @classmethod
    def from_env(cls) -> "Paths":
        return cls()

    @property
    def devices_dir(self) -> Path:
        return self.root / "devices"

    @property
    def dist(self) -> Path:
        """Cache for downloaded binary distributions, ``root/dist``.

        Design:
            One shared cache directory for any downloaded binary, so a
            caller with a new one to cache reaches for this property instead
            of inventing its own location.
        """
        return self.root / "dist"

    @property
    def list_config_path(self) -> Path:
        """The ledger-style YAML declaring `gunkata devices`'s extra columns."""
        return self.devices_dir / "list-config.yaml"

    def device_dir(self, serial: str) -> Path:
        """serial's own directory, everything about it nested underneath."""
        return self.devices_dir / serial

    def device_name_path(self, serial: str) -> Path:
        """serial's persisted name -- the file's entire contents, nothing else."""
        return self.device_dir(serial) / "name"

    def device_tags_path(self, serial: str) -> Path:
        """serial's tags, one per line."""
        return self.device_dir(serial) / "tags"

    def device_note_path(self, serial: str) -> Path:
        """serial's append-only, timestamped note log."""
        return self.device_dir(serial) / "note"

    def device_settings_path(self, serial: str) -> Path:
        """serial's persisted GUNKATA_* environment overrides, one KEY=VALUE per line."""
        return self.device_dir(serial) / "settings"
