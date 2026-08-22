"""Per-serial metadata a user attaches locally: a name, tags, and a note log.

Each kind lives in its own plain-text file under GUNKATA_ROOT/devices/<serial>/
-- `name`, `tags`, `note` -- one lane per file rather than one shared document,
so tagging a device can never race a concurrent rename of it, and each file
reads exactly as it looks with `cat`. See gunkata.device.DeviceSettingsStore
for that same serial directory's `settings` file.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from gunkata.common.paths import Paths

_NOTE_ENTRY = "### {stamp}\n{message}\n\n"


@dataclass(frozen=True)
class DeviceInfo:
    """One device's persisted name and tags. Notes are append-only and live
    outside this shape -- see DeviceInfoStore.add_note.

    Attributes:
        name: The user-given name, or None if never set.
        tags: This device's tags, sorted for deterministic display.
    """

    name: str | None = None
    tags: tuple[str, ...] = ()


class DeviceInfoStore:
    """Reads and writes one device's name, tags, and note log.

    Args:
        paths: Resolves where each of those files lives for a given serial.
    """

    def __init__(self, paths: Paths):
        self._paths = paths

    def load(self, serial: str) -> DeviceInfo:
        """Load one serial's name and tags.

        Returns:
            The persisted name/tags; a field with no file yet reads as None
            or () respectively -- an unset device is a fact, not an error.
        """
        return DeviceInfo(name=self._load_name(serial), tags=self._load_tags(serial))

    def set_name(self, serial: str, name: str) -> None:
        """Set serial's persisted name, replacing whatever was there before."""
        path = self._paths.device_name_path(serial)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n")

    def add_tag(self, serial: str, tag: str) -> None:
        """Add tag to serial's tags. A no-op if it's already present."""
        self._write_tags(serial, {*self._load_tags(serial), tag})

    def remove_tag(self, serial: str, tag: str) -> None:
        """Remove tag from serial's tags. A no-op if it isn't present."""
        self._write_tags(serial, set(self._load_tags(serial)) - {tag})

    def add_note(self, serial: str, message: str, when: datetime | None = None) -> None:
        """Append message to serial's note log, prepended by a timestamp.

        Args:
            message: The note text; leading/trailing whitespace is stripped.
            when: The moment to record; defaults to now (UTC). Exposed so a
                caller (a test, or a note composed earlier than it's saved)
                can pin the timestamp instead of racing the clock.
        """
        path = self._paths.device_note_path(serial)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        with path.open("a") as f:
            f.write(_NOTE_ENTRY.format(stamp=stamp, message=message.strip()))

    def _load_name(self, serial: str) -> str | None:
        path = self._paths.device_name_path(serial)
        if not path.exists():
            return None
        return path.read_text().strip() or None

    def _load_tags(self, serial: str) -> tuple[str, ...]:
        path = self._paths.device_tags_path(serial)
        if not path.exists():
            return ()
        return tuple(
            sorted(line.strip() for line in path.read_text().splitlines() if line.strip())
        )

    def _write_tags(self, serial: str, tags: set[str]) -> None:
        path = self._paths.device_tags_path(serial)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{tag}\n" for tag in sorted(tags)))
