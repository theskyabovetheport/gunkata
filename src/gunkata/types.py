"""Data shapes produced by running a command on a device.

These live apart from their producers because both the blocking path
(``gunkata.shell``) and the streaming path (``gunkata.stream``) serve them, and
a module holding them next to either one would make the two import each other.
"""

from dataclasses import dataclass


class ShellError(RuntimeError):
    """A device command exited non-zero on its own.

    Args:
        command: The command as it was sent to the device, before su wrapping.
        stderr: Everything the command wrote to stderr.
        rc: The exit status the device reported.

    Design:
        Carries the three facts separately rather than a formatted string so a
        caller can branch on ``rc`` without re-parsing the message. A dropped
        adb transport reports rc 255 with empty stderr, so the message names the
        absence rather than trailing off after a bare colon.
    """

    def __init__(self, command: str, stderr: str, rc: int):
        self.command = command
        self.stderr = stderr
        self.rc = rc
        super().__init__(
            f"command {command!r} failed (rc={rc}): {stderr or '<no stderr>'}"
        )


@dataclass
class ShellResult:
    """The complete outcome of a device command that ran to completion.

    Attributes:
        command: The command as it was sent to the device, before su wrapping.
        stdout: Everything the command wrote to stdout.
        stderr: Everything the command wrote to stderr.
        rc: The exit status the device reported.
    """

    command: str
    stdout: str
    stderr: str
    rc: int

    @property
    def ok(self) -> bool:
        """Whether the command reported success."""
        return self.rc == 0

    @property
    def output(self) -> str:
        """Both streams concatenated, stdout first, with no separator inserted."""
        return f"{self.stdout}{self.stderr}"
