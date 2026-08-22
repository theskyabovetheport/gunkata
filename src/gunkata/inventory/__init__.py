"""Local bookkeeping about adb-visible devices: names, tags, notes, and the
list-config.yaml column spec the `gunkata devices` table renders.

Distinct from `gunkata.device.Device`, which operates one already-selected
device; these track metadata about every device gunkata's operator knows
about, whether or not it is the one currently bound.
"""

from .info import DeviceInfo, DeviceInfoStore
from .list_config import (
    DEFAULT_LIST_CONFIG_YAML,
    KINDS,
    Column,
    Getter,
    ListConfig,
    ListConfigError,
)
from .roster import DeviceRoster
