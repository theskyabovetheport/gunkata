import subprocess


class AdbError(RuntimeError):
    pass


class Adb:
    def __init__(self, serial: str | None = None):
        if serial is None:
            serial = self._get_one_serial()
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
    def list_serials() -> list[str]:
        completed = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, check=True
        )
        return [
            fields[0]
            for line in completed.stdout.splitlines()[1:]
            if len(fields := line.split()) == 2 and fields[1] == "device"
        ]

    @classmethod
    def _get_one_serial(cls) -> str:
        serials = cls.list_serials()
        if not serials:
            raise AdbError("no adb device connected")
        if len(serials) > 1:
            raise AdbError(f"multiple adb devices connected; pass a serial explicitly")
        return serials[0]
