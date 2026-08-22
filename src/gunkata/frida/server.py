"""frida-server on one device: provision, run detached or scoped, reap."""

import logging
import os
import re
import time
from collections.abc import Generator
from contextlib import contextmanager

from ..shell import Shell
from .dep import import_frida
from .repo import ServerRepo, server_repo
from .settings import FridaSettings

logger = logging.getLogger(__name__)

_DEVICE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


class FridaServerError(RuntimeError):
    """frida-server could not be brought to the requested state on the device."""


class FridaNotReadyError(RuntimeError):
    """frida-server on this server's serial did not answer within the timeout."""


class FridaServer:
    """frida-server on one device: provision it, run it, and reap it.

    Args:
        shell: Root shell the binary is pushed and run under. frida-server needs
            root to ptrace, so this must be a shell whose user can gain it.
        repo: Source of the uncompressed frida-server binary to push, or None
            to default to this process's configured repo, `server_repo()`.
        version: frida version to provision, or None to default to the installed
            frida package's version.
        device_path: Where the binary lives on the device, or None to default
            to settings.device_path.
        port: Loopback TCP port frida-server binds on the device, or None to
            default to settings.port.
        assume_running: Whether to trust that frida-server is already running
            rather than probe the device for it, or None to default to
            settings.assume_running.
        settings: Timeouts and fallback device_path/port/assume_running,
            resolved from the environment. None builds a fresh FridaSettings.

    Design:
        Two lifetimes share one command builder and one pid choke point. Detached
        ``start`` uses ``-D`` so the launch returns and the daemon outlives the
        adb invocation; scoped ``running`` omits ``-D`` so the server stays a
        child of the adb remote shell and the Stream reaps it on exit. Every
        value interpolated into a device command is validated first -- the path
        and port in the constructor, pids in ``running_pids`` -- because this
        class assembles the full command text itself, and nothing downstream
        re-validates a value once it's part of that text.

        assume_running is a trust boundary, not a cache. A caller sets it when
        something outside this instance owns frida-server's lifecycle (a boot
        script, another process) and this instance must not probe or touch the
        device for it: ``is_running`` reports the assumption without a device
        round trip, ``start`` and ``running`` are no-ops, and ``stop`` refuses
        outright rather than tear down a server this instance never launched.
        ``running_pids`` is unaffected -- it stays the one live, device-derived
        answer for callers that need real pids.

        A bare Shell is the whole dependency: frida's own transport does its
        own device multiplexing, so provisioning and running frida-server
        needs nothing else host-side, and ``get_device`` reads the same
        shell's ``serial`` to bind the frida device it waits on -- one
        object names both the adb target and the frida target, so the two
        can never drift apart. repo defaults to `server_repo()` when
        omitted, so a caller with no opinion about where archives live states
        none.
    """

    def __init__(
        self,
        shell: Shell,
        repo: ServerRepo | None = None,
        *,
        version: str | None = None,
        device_path: str | None = None,
        port: int | None = None,
        assume_running: bool | None = None,
        settings: FridaSettings | None = None,
    ):
        settings = settings if settings is not None else FridaSettings()
        if device_path is None:
            device_path = settings.device_path
        if port is None:
            port = settings.port
        if assume_running is None:
            assume_running = settings.assume_running
        if not _DEVICE_PATH.match(device_path):
            raise ValueError(f"unsafe frida-server device path: {device_path!r}")
        if not 1 <= port <= 65535:
            raise ValueError(f"port out of range: {port}")
        self._shell = shell
        self._repo = repo if repo is not None else server_repo()
        self._version = version
        self._device_path = device_path
        self._port = port
        self._assume_running = assume_running
        self._settings = settings

    def install(self) -> str:
        """Push the binary to the device and mark it executable.

        Returns:
            The device path the binary now lives at.

        Raises:
            UnsupportedAbiError: The device ABI has no frida build.
            VersionUnresolvedError: No version given and frida is not installed.
            ServerAssetError: The matching archive is missing from the repo and
                autodownload_server_binary is not set.
            BinaryDownloadError: autodownload_server_binary is set and
                the download failed.
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
            running server is returned, never a second copy. Empty when
            assume_running is set, since this instance never launches a
            server it does not own.

        Raises:
            ShellError: The launch command exited non-zero.
            FridaServerError: The server did not appear within the start timeout.
        """
        if self._assume_running:
            logger.info("frida-server assumed running; start is a no-op")
            return []
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
            FridaServerError: assume_running is set; this instance does not
                own frida-server's lifecycle and refuses to tear it down.
            ShellError: The kill command exited non-zero.
        """
        if self._assume_running:
            raise FridaServerError(
                "frida-server assume_running is set; this instance does not "
                "own its lifecycle and refuses to stop it"
            )
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
        """Whether frida-server is running on the device right now.

        Returns:
            True unconditionally when assume_running is set, without a
            device round trip; otherwise the live pidof-derived answer.
        """
        if self._assume_running:
            return True
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
            This server, running, for the body of the block. When
            assume_running is set, this is a no-op that yields immediately
            without launching or reaping anything, since this instance never
            takes ownership of a server it does not own.

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
        if self._assume_running:
            yield self
            return
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

    def get_device(
        self, timeout: float | None = None, poll: float | None = None
    ) -> "frida.core.Device":
        """Get the connected frida device for this server's serial, once it answers.

        Args:
            timeout: Seconds to wait for both the device to appear and its
                server to answer, or None to default to
                settings.connect_timeout_seconds.
            poll: Seconds between server-readiness probes, or None to default
                to settings.connect_poll_seconds.

        Returns:
            A ``frida.core.Device`` bound to this server's serial, whose
            server has answered at least one request.

        Raises:
            FridaUnavailableError: frida is not installed.
            FridaNotReadyError: The server did not answer within ``timeout``.

        Design:
            ``get_device(serial)``, not ``get_usb_device()``: the latter picks
            the first USB device and would misbind when several are attached,
            so it must be the one serial this server was built for. That
            call's own timeout waits for the device to appear; server
            readiness is separate -- the adb transport is present at once,
            the frida-server port is not -- so a cheap RPC is polled past the
            not-yet-listening race, and a serial-named refusal is raised on
            timeout with the last frida error as its cause.
        """
        if timeout is None:
            timeout = self._settings.connect_timeout_seconds
        if poll is None:
            poll = self._settings.connect_poll_seconds
        serial = self._shell.serial
        frida = import_frida()
        manager = frida.get_device_manager()
        device = manager.get_device(serial, timeout=timeout)
        deadline = time.monotonic() + timeout
        last = None
        while True:
            try:
                device.query_system_parameters()
                return device
            except frida.Error as exc:
                last = exc
            if time.monotonic() >= deadline:
                raise FridaNotReadyError(
                    f"frida-server on {serial!r} did not answer within {timeout}s"
                ) from last
            time.sleep(poll)

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
        deadline = time.monotonic() + self._settings.start_timeout_seconds
        while True:
            pids = self.running_pids()
            if pids:
                return pids
            if time.monotonic() >= deadline:
                raise FridaServerError(
                    f"frida-server did not come up at 127.0.0.1:{self._port} "
                    f"({self._device_path})"
                )
            time.sleep(self._settings.poll_interval_seconds)

    def _await_gone(self) -> list[int]:
        deadline = time.monotonic() + self._settings.stop_grace_seconds
        while time.monotonic() < deadline:
            if not self.running_pids():
                return []
            time.sleep(self._settings.poll_interval_seconds)
        return self.running_pids()
