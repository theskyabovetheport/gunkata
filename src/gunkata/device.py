import subprocess
from enum import Enum
from .adb import Adb
from .logcat import Level, Logcat
from .procmaps import ProcMaps
from .ps import Ps
from .settings import SuBinary
from .shell import Shell


class DeviceState(Enum):
    device = "device"


class Device:
    """
    Android device, operated through adb.
    """

    def __init__(self, adb: Adb, su_binary: str | None = None):
        self._adb = adb
        self._su = SuBinary.for_device(adb.serial, su_binary)
        self._has_su = None

    @property
    def serial(self) -> str:
        return self._adb.serial

    def get_state(self) -> str:
        return self._adb(["get-state"], capture_output=True, text=True).stdout.strip()

    def wait_for_state(self, state: DeviceState | str):
        self._adb([f"wait-for-{DeviceState(state).value}"])

    def shell(self, user: str | None = None) -> Shell:
        if user is None:
            user = "root" if self.has_su else "shell"
        return Shell(self._adb, user=user, su=self._su)

    def logcat(
        self,
        tail: int | None = 1,
        follow: bool = True,
        tags: dict[str, Level] | None = None,
    ) -> Logcat:
        """Read this device's log buffers as parsed records.

        Args:
            tail: How many already-buffered records to start from. None starts
                at the beginning of the ring buffer.
            follow: Keep yielding records as the device writes them.
            tags: Minimum level to let through for each named tag; tags not
                listed are silenced. None keeps every tag.

        Returns:
            A spec that starts its own logcat each time it is iterated.

        Raises:
            ValueError: tail is below one, which logcat cannot express.
        """
        return Logcat(self.shell(), tail=tail, follow=follow, tags=tags)

    def procmaps(self) -> ProcMaps:
        """Read this device's processes' /proc/<pid>/maps.

        Returns:
            A reader that resolves a pid or process name to that file's bytes.
        """
        return ProcMaps(self.shell())

    def ps(self) -> Ps:
        """Read this device's process list.

        Returns:
            A cached view over `ps -A`; see Ps for its caching behaviour.
        """
        return Ps(self.shell())

    @property
    def has_su(self) -> bool:
        if self._has_su is None:
            self._has_su = self._check_su()
        return self._has_su

    def _check_su(self) -> bool:
        cp = self._adb(
            ["shell", f"command -v {self._su.name}"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        return cp.returncode == 0
