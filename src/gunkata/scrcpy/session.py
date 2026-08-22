"""Supervising scrcpy inside its frame, relaunching it across a device reboot."""

import logging
import os
import subprocess
import time

from ..device import Device
from .repo import ScrcpyRepo, scrcpy_repo
from .settings import ScrcpySettings
from .xephyr import Xephyr

logger = logging.getLogger(__name__)


class ScrcpyLaunchError(RuntimeError):
    """scrcpy kept exiting almost immediately; relaunching forever would spin."""


class ScrcpyBootTimeoutError(RuntimeError):
    """The device did not report sys.boot_completed within the configured timeout."""


class ScrcpySession:
    """Mirrors one device inside a frame that outlives it, relaunching scrcpy on reboot.

    Args:
        device: The device to mirror. Its serial names both the frame's
            title and the ``-s`` scrcpy is launched with.
        repo: Source of the extracted scrcpy binary, or None to default to
            this process's configured repo, ``scrcpy_repo()``.
        settings: Frame size and timing, resolved from the environment. None
            builds a fresh ScrcpySettings.
        extra_args: Extra arguments appended to every scrcpy launch, passed
            through from the CLI's own passthrough argv.

    Design:
        Takes a Device, not a bare Shell: relaunching after a reboot needs
        both ``wait_for_state`` (the adb transport coming back) and
        ``shell()`` (a fresh su probe once it has), and Device is the one
        object that owns both for one serial. A new Shell is built each
        boot-completed poll round rather than reused, so a relaunch after
        reboot re-resolves su the same way a fresh ``Device()`` would, not a
        binding that predates the reboot.

        The frame is started once and only Xephyr's own exit ends the
        session; any scrcpy exit in between -- device drop, crash, the user
        closing scrcpy's own window without closing the frame -- is always
        followed by a relaunch, once the device is back. This is the whole
        mechanism the geometry survives by: the frame is the window a WM
        manages, and it is asked to do nothing it was not already going to
        do (stay where it is).
    """

    def __init__(
        self,
        device: Device,
        repo: ScrcpyRepo | None = None,
        settings: ScrcpySettings | None = None,
        extra_args: list[str] | None = None,
    ):
        self._device = device
        self._repo = repo if repo is not None else scrcpy_repo()
        # pyright can't see the env-backed default through validation_alias.
        self._settings = settings if settings is not None else ScrcpySettings()  # pyright: ignore
        self._extra_args = extra_args if extra_args is not None else []

    def run(self) -> None:
        """Run scrcpy inside a fresh frame until the frame itself closes.

        Raises:
            UnsupportedHostError: This host has no scrcpy release build.
            ValueError: The configured scrcpy version is not a strict
                release token.
            ScrcpyAssetError: The matching scrcpy archive is missing and
                autodownload_binary is not set.
            BinaryDownloadError: autodownload_binary is set and the download
                failed.
            ScrcpyChecksumError: autodownload_binary is set and the
                downloaded archive did not match its published checksum.
            NoDisplayError: No host X server is available to nest inside.
            XephyrUnavailableError: The Xephyr binary is not on PATH.
            FrameDisplayError: The frame's own X display could not be
                queried for its size.
            ScrcpyBootTimeoutError: The device did not come back within
                boot_timeout_seconds after a drop.
            ScrcpyLaunchError: scrcpy kept exiting almost immediately, past
                launch_failure_limit consecutive times.

        Design:
            The binary is resolved before the frame is started, so a
            download or checksum failure never leaves an orphan frame
            on-screen for the caller to notice and close by hand.
        """
        binary = self._repo.resolve()
        serial = self._device.serial
        frame = Xephyr(
            title=f"gunkata:{serial}",
            placeholder=f"waiting for\n{serial}",
            settings=self._settings,
        )
        with frame.running() as running:
            self._loop(binary, running)

    def _loop(self, binary, frame: Xephyr) -> None:
        consecutive_failures = 0
        while frame.poll() is None:
            self._await_device()
            process = self._launch(binary, frame)
            launched_against = frame.screen_size()
            started = time.monotonic()
            try:
                resized = self._await_exit(process, frame, launched_against)
            finally:
                rc = self._reap(process)
            if frame.poll() is not None:
                break
            if resized:
                logger.info(
                    "frame resized, relaunching scrcpy",
                    extra={"was": launched_against, "now": frame.screen_size()},
                )
                # scrcpy is already reaped here, so the probe's own pointer
                # motion cannot reach the device.
                frame.check_pointer_reaches_the_screen()
                consecutive_failures = 0
                continue
            lived = time.monotonic() - started
            if lived < self._settings.min_uptime_seconds:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
            if consecutive_failures >= self._settings.launch_failure_limit:
                raise ScrcpyLaunchError(
                    f"scrcpy exited with rc={rc} after {lived:.1f}s, "
                    f"{consecutive_failures} times in a row; "
                    f"argv={self._argv(binary)!r}"
                )

    def _await_device(self) -> None:
        """Block until the device is present and has finished booting.

        Raises:
            ScrcpyBootTimeoutError: sys.boot_completed never reported "1"
                within boot_timeout_seconds of the transport coming back.

        Design:
            ``wait_for_state("device")`` returns as soon as adbd answers,
            well before app_process can host scrcpy's own server -- the same
            gap scripts/run_emulator.sh polls past for a fresh emulator boot,
            here for a reboot mid-session instead.
        """
        self._device.wait_for_state("device")
        deadline = time.monotonic() + self._settings.boot_timeout_seconds
        while True:
            result = self._device.shell().sh("getprop sys.boot_completed")
            if result.stdout.strip() == "1":
                return
            if time.monotonic() >= deadline:
                raise ScrcpyBootTimeoutError(
                    f"{self._device.serial} did not report sys.boot_completed=1 "
                    f"within {self._settings.boot_timeout_seconds}s"
                )
            time.sleep(self._settings.poll_interval_seconds)

    def _argv(self, binary) -> list[str]:
        """Build scrcpy's argv for one launch inside the frame.

        Design:
            No window position or size is passed. The frame's nested screen
            follows whatever size the host WM gives the frame, so any
            geometry named here would be right only until the first resize;
            matchbox maximizes scrcpy against the nested screen's current
            size instead, resize after resize. ``--fullscreen`` letterboxes
            the device's own aspect ratio inside that, which scrcpy paints
            in full -- pass ``--render-fit=stretched`` through to fill the
            frame edge to edge instead.
        """
        return [
            str(binary),
            "-s",
            self._device.serial,
            "--fullscreen",
            *self._extra_args,
        ]

    def _launch(self, binary, frame: Xephyr) -> subprocess.Popen:
        """Start scrcpy inside frame's display, isolated from the host's own.

        Design:
            SDL_VIDEODRIVER=x11 is the load-bearing line: without it, SDL can
            pick a Wayland backend in a Wayland session and open scrcpy's
            window on the host compositor, escaping the frame entirely while
            appearing to work. WAYLAND_DISPLAY is cleared for the same
            reason, belt and braces. ADB names the same adb gunkata.adb.Adb
            invokes, and SCRCPY_SERVER_PATH names the extracted archive's own
            bundled server as a sibling of binary -- both remove any
            dependence on scrcpy's own search order or the archive's bundled
            adb, which could otherwise fight the one this process already
            uses.
        """
        env = dict(os.environ)
        env["DISPLAY"] = frame.display
        env["SDL_VIDEODRIVER"] = "x11"
        env.pop("WAYLAND_DISPLAY", None)
        env["SCRCPY_SERVER_PATH"] = str(binary.parent / "scrcpy-server")
        env["ADB"] = "adb"
        argv = self._argv(binary)
        logger.info("launching scrcpy", extra={"display": frame.display, "argv": argv})
        return subprocess.Popen(argv, env=env)

    def _await_exit(
        self,
        process: subprocess.Popen,
        frame: Xephyr,
        launched_against: tuple[int, int],
    ) -> bool:
        """Wait until scrcpy exits, the frame closes, or the frame changes size.

        Args:
            process: The running scrcpy.
            frame: The frame it is running inside.
            launched_against: The frame's screen size when this scrcpy was
                launched, the value a change is measured against.

        Returns:
            True when the frame's screen changed size, meaning this scrcpy is
            stale and its caller must replace it; False when it ended for any
            other reason.

        Design:
            A resize is grounds for replacing scrcpy rather than trusting it
            to re-fit: verified on a real device, clicks land progressively
            too high after the frame is resized, because scrcpy keeps mapping
            them against the geometry it started with, while a fresh scrcpy is
            accurate. Relaunching is what the session already does on every
            device drop, so this reuses that path rather than adding a second
            way for scrcpy to be replaced.
        """
        while process.poll() is None and frame.poll() is None:
            if frame.screen_size() != launched_against:
                return True
            time.sleep(self._settings.poll_interval_seconds)
        return False

    def _reap(self, process: subprocess.Popen) -> int | None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._settings.stop_grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        return process.returncode
