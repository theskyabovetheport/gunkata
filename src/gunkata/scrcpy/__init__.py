"""scrcpy integration: mirror a device inside a frame that outlives its reboots."""

from .repo import (
    HostArch,
    ScrcpyAssetError,
    ScrcpyChecksumError,
    ScrcpyRepo,
    UnsupportedHostError,
    scrcpy_repo,
)
from .session import ScrcpyBootTimeoutError, ScrcpyLaunchError, ScrcpySession
from .settings import ScrcpySettings
from .xephyr import (
    FrameDisplayError,
    MatchboxUnavailableError,
    NoDisplayError,
    Xephyr,
    XephyrUnavailableError,
)
