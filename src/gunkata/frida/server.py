"""frida-server on one device: provision, run detached or scoped, reap."""

import logging
import os
import re
import time
from collections.abc import Generator
from contextlib import contextmanager

from ..shell import Shell
from .repo import ServerRepo

logger = logging.getLogger(__name__)

_DEVICE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


class FridaServerError(RuntimeError):
    """frida-server could not be brought to the requested state on the device."""


class FridaServer:
    """frida-server on one device: provision it, run it, and reap it.

    Args:
        shell: Root shell the binary is pushed and run under. frida-server needs
            root to ptrace, so this must be a shell whose user can gain it.
        repo: Source of the uncompressed frida-server binary to push.
        version: frida version to provision, or None to default to the installed
            frida package's version.
        device_path: Where the binary lives on the device.
        port: Loopback TCP port frida-server binds on the device.

    Design:
        Two lifetimes share one command builder and one pid choke point. Detached
        ``start`` uses ``-D`` so the launch returns and the daemon outlives the
        adb invocation; scoped ``running`` omits ``-D`` so the server stays a
        child of the adb remote shell and the Stream reaps it on exit. Every
        value interpolated into a device command is validated first -- the path
        and port in the constructor, pids in ``running_pids`` -- because the
        shell wraps commands in ``su ... sh -c '...'`` without escaping.
    """

    DEFAULT_DEVICE_PATH = "/data/local/tmp/frida-server"
    DEFAULT_PORT = 27042
    _START_TIMEOUT_SECONDS = 10.0
    _STOP_GRACE_SECONDS = 3.0
    _POLL_INTERVAL_SECONDS = 0.1

    def __init__(
        self,
        shell: Shell,
        repo: ServerRepo,
        *,
        version: str | None = None,
        device_path: str = DEFAULT_DEVICE_PATH,
        port: int = DEFAULT_PORT,
    ):
        if not _DEVICE_PATH.match(device_path):
            raise ValueError(f"unsafe frida-server device path: {device_path!r}")
        if not 1 <= port <= 65535:
            raise ValueError(f"port out of range: {port}")
        self._shell = shell
        self._repo = repo
        self._version = version
        self._device_path = device_path
        self._port = port

    def install(self) -> str:
        """Push the binary to the device and mark it executable.

        Returns:
            The device path the binary now lives at.

        Raises:
            UnsupportedAbiError: The device ABI has no frida build.
            VersionUnresolvedError: No version given and frida is not installed.
            ServerAssetError: The matching archive is missing from the repo.
            ShellError: The push or chmod failed.
        """
        with self._repo.extracted(self._shell, self._version) as local:
            self._shell.push_file(self._device_path, str(local), inherit_owner=False)
            self._shell.chmod(self._device_path, "755")
        logger.info("frida-server installed", extra={"path": self._device_path})
        return self._device_path

    def _ensure_installed(self) -> None:
        if not self._shell.file_exists(self._device_path):
            self.install()

    def start(self) -> list[int]:
        """Launch frida-server detached so it outlives this call.

        Returns:
            The pid(s) frida-server is running under. Idempotent: an already
            running server is returned, never a second copy.

        Raises:
            ShellError: The launch command exited non-zero.
            FridaServerError: The server did not appear within the start timeout.
        """
        running = self.running_pids()
        if running:
            logger.info("frida-server already running", extra={"pids": running})
            return running
        self._ensure_installed()
        self._shell.check_sh(self._detached_command())
        pids = self._await_running()
        logger.info("frida-server started", extra={"pids": pids, "port": self._port})
        return pids

    def stop(self) -> list[int]:
        """Kill any running frida-server, escalating to SIGKILL if needed.

        Returns:
            The pid(s) killed, or an empty list when nothing was running.

        Raises:
            ShellError: The kill command exited non-zero.
        """
        pids = self.running_pids()
        if not pids:
            return []
        self._shell.check_sh(self._kill_command(pids))
        survivors = self._await_gone()
        if survivors:
            self._shell.check_sh(self._kill_command(survivors, force=True))
            self._await_gone()
        logger.info("frida-server stopped", extra={"pids": pids})
        return pids

    def is_running(self) -> bool:
        """Whether frida-server is running on the device right now."""
        return bool(self.running_pids())

    def running_pids(self) -> list[int]:
        """The pid(s) frida-server runs under, empty when it is not running.

        Returns:
            One entry per running frida-server process.
        """
        return self._shell.pidof(self._process_name())

    @contextmanager
    def running(self) -> Generator["FridaServer", None, None]:
        """Run frida-server for the duration of a ``with`` block, reaping it after.

        Yields:
            This server, running, for the body of the block.

        Raises:
            FridaServerError: A server is already running (a scoped run must own
                the lifetime), or it never came up within the start timeout.
            ShellError: The launch failed.

        Design:
            The command omits ``-D`` on purpose: frida-server stays foreground as
            a child of the adb remote shell, so closing the Stream kills the
            local adb and adbd tears down the remote process group with it -- the
            same reap logcat relies on. ``stop`` runs afterwards as a safety net,
            in case frida-server ignored the hang-up and survived. It is not run
            verbose: an unread stdout pipe would fill at ~64KB and stall the
            server.
        """
        if self.running_pids():
            raise FridaServerError(
                "frida-server already running; a scoped run needs exclusive use"
            )
        self._ensure_installed()
        stream = self._shell.stream(self._foreground_command())
        try:
            self._await_running()
            yield self
        finally:
            stream.close()
            self.stop()

    def _detached_command(self) -> str:
        # -D daemonizes, but the daemon still inherits adb's stdout pipe; adb
        # shell blocks on EOF until it is closed, so redirect all three standard
        # streams to /dev/null to hand adb its EOF and let the launch return.
        return (
            f"{self._device_path} -D -l 127.0.0.1:{self._port} "
            f"</dev/null >/dev/null 2>&1"
        )

    def _foreground_command(self) -> str:
        return f"{self._device_path} -l 127.0.0.1:{self._port}"

    def _process_name(self) -> str:
        return os.path.basename(self._device_path)

    def _kill_command(self, pids: list[int], force: bool = False) -> str:
        flag = "-9 " if force else ""
        return f"kill {flag}{' '.join(str(pid) for pid in pids)}"

    def _await_running(self) -> list[int]:
        deadline = time.monotonic() + self._START_TIMEOUT_SECONDS
        while True:
            pids = self.running_pids()
            if pids:
                return pids
            if time.monotonic() >= deadline:
                raise FridaServerError(
                    f"frida-server did not come up at 127.0.0.1:{self._port} "
                    f"({self._device_path})"
                )
            time.sleep(self._POLL_INTERVAL_SECONDS)

    def _await_gone(self) -> list[int]:
        deadline = time.monotonic() + self._STOP_GRACE_SECONDS
        while time.monotonic() < deadline:
            if not self.running_pids():
                return []
            time.sleep(self._POLL_INTERVAL_SECONDS)
        return self.running_pids()
