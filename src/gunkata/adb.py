import os
import subprocess
from dataclasses import dataclass


class AdbError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdbDeviceEntry:
    """One line of `adb devices`: a serial and the state adb reports for it."""

    serial: str
    state: str


class Adb:
    def __init__(self, serial: str | None = None):
        """Scope this instance to serial, by priority: serial, then $ANDROID_SERIAL.

        Raises:
            AdbError: serial is None, $ANDROID_SERIAL is unset, and zero or
                more than one device is currently connected.

        Design:
            $ANDROID_SERIAL is checked here, not by callers -- the same
            environment variable real `adb` itself honors, so a caller that
            never passes serial still gets the ambient device every other
            adb-based tool in the same shell would target.
        """
        if serial is None:
            serial = os.environ.get("ANDROID_SERIAL") or self._get_one_serial()
        self.serial = serial

    def __call__(
        self, args: list[str], **subprocess_run_kwargs
    ) -> subprocess.CompletedProcess:
        return subprocess.run(self._argv(args), **subprocess_run_kwargs)

    def popen(self, args: list[str], **subprocess_popen_kwargs) -> subprocess.Popen:
        """Start an adb invocation against this device without waiting for it.

        Args:
            args: adb subcommand and its arguments, such as ``["shell", "logcat"]``.
            **subprocess_popen_kwargs: Forwarded verbatim to ``subprocess.Popen``.

        Returns:
            The running process, scoped to this device's serial. Its lifetime
            belongs to the caller, which must reap it.

        Raises:
            OSError: The adb executable is not on PATH.

        Design:
            Shares ``_argv`` with ``__call__`` so device scoping is expressed
            once and a flag added there reaches both spawn modes. Pipe and
            text-mode policy stay with the caller, which owns the pipes.
        """
        return subprocess.Popen(self._argv(args), **subprocess_popen_kwargs)

    def _argv(self, args: list[str]) -> list[str]:
        """Build the full command line for a device-scoped adb invocation."""
        return ["adb", "-s", self.serial, *args]

    @staticmethod
    def list_devices() -> list[AdbDeviceEntry]:
        """Every serial adb currently reports, whatever state it's in.

        Returns:
            One entry per line of `adb devices`, in the order adb reported
            them -- offline and unauthorized serials included, unlike
            list_serials.
        """
        completed = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, check=True
        )
        return [
            AdbDeviceEntry(fields[0], fields[1])
            for line in completed.stdout.splitlines()[1:]
            if len(fields := line.split()) == 2
        ]

    @staticmethod
    def list_serials() -> list[str]:
        return [d.serial for d in Adb.list_devices() if d.state == "device"]

    @classmethod
    def _get_one_serial(cls) -> str:
        serials = cls.list_serials()
        if not serials:
            raise AdbError("no adb device connected")
        if len(serials) > 1:
            raise AdbError("multiple adb devices connected; pass a serial explicitly")
        return serials[0]


class AdbFactory:
    """Builds Adb instances and lists adb-visible devices.

    Design:
        The injectable seam for a caller that fans out over more than one
        device -- one Adb per serial -- rather than being bound to a single
        instance the way most callers are: it takes an AdbFactory instead of
        importing Adb itself, so a test can substitute one without patching
        a name inside the module under test.
    """

    def __call__(self, serial: str | None = None) -> Adb:
        return Adb(serial)

    def list_devices(self) -> list[AdbDeviceEntry]:
        return Adb.list_devices()
