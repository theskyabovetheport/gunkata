"""Environment-resolved settings for provisioning and running scrcpy in its frame."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScrcpySettings(BaseSettings):
    """How scrcpy is provisioned, framed, and relaunched across device reboots.

    Attributes:
        version: scrcpy release to provision, in its own ``X.Y`` or ``X.Y.Z``
            tag spelling.
        autodownload_binary: Whether ScrcpyRepo may fetch a missing scrcpy
            release archive from GitHub instead of refusing.
        xephyr_binary: The nested X server binary to run as the frame.
        xmessage_binary: The optional binary that paints the frame's
            placeholder -- what shows in the frame whenever scrcpy is not
            covering it. Missing from PATH, it is logged and skipped, since
            it is not needed to mirror a device; without it that gap is
            bare black.
        matchbox_binary: The window manager run inside the frame to keep
            scrcpy's own window maximized against it -- without one, an
            unmanaged X11 client opens at its own preferred size, floating
            unaligned inside the frame rather than filling it.
        frame_ready_timeout_seconds: How long to wait for the frame to report
            its display number before giving up.
        boot_timeout_seconds: How long to wait for a device that dropped to
            report sys.boot_completed before giving up on a relaunch.
        poll_interval_seconds: How often to re-check device and process state
            while awaiting any of the state changes above.
        stop_grace_seconds: How long to wait for a terminated process to exit
            before escalating to SIGKILL.
        min_uptime_seconds: How long a scrcpy launch must survive to count as
            healthy rather than a failure toward launch_failure_limit.
        launch_failure_limit: Consecutive scrcpy launches shorter than
            min_uptime_seconds before the session refuses instead of
            relaunching forever.

    Design:
        Same shape as FridaSettings: one BaseSettings per concern, built
        explicitly wherever a caller needs scrcpy config, rather than each
        consumer restating its own copy of these defaults. Colocated in its
        own module rather than beside a single consumer, since ScrcpyRepo,
        Xephyr, and ScrcpySession all read it -- the same condition that
        moved FridaSettings out of frida/server.py.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    version: str = Field("4.1", validation_alias="GUNKATA_SCRCPY_VERSION")
    autodownload_binary: bool = Field(
        False, validation_alias="GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY"
    )
    xephyr_binary: str = Field("Xephyr", validation_alias="GUNKATA_SCRCPY_XEPHYR_BINARY")
    xmessage_binary: str = Field(
        "xmessage", validation_alias="GUNKATA_SCRCPY_XMESSAGE_BINARY"
    )
    matchbox_binary: str = Field(
        "matchbox-window-manager", validation_alias="GUNKATA_SCRCPY_MATCHBOX_BINARY"
    )
    frame_ready_timeout_seconds: float = Field(
        10.0, validation_alias="GUNKATA_SCRCPY_FRAME_READY_TIMEOUT_SECONDS"
    )
    boot_timeout_seconds: float = Field(
        180.0, validation_alias="GUNKATA_SCRCPY_BOOT_TIMEOUT_SECONDS"
    )
    poll_interval_seconds: float = Field(
        0.5, validation_alias="GUNKATA_SCRCPY_POLL_INTERVAL_SECONDS"
    )
    stop_grace_seconds: float = Field(
        3.0, validation_alias="GUNKATA_SCRCPY_STOP_GRACE_SECONDS"
    )
    min_uptime_seconds: float = Field(
        2.0, validation_alias="GUNKATA_SCRCPY_MIN_UPTIME_SECONDS"
    )
    launch_failure_limit: int = Field(
        3, validation_alias="GUNKATA_SCRCPY_LAUNCH_FAILURE_LIMIT"
    )
