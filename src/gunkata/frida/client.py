"""Connecting a frida client to a running frida-server, bound to an adb serial."""

import logging
import time
from collections.abc import Callable

from .dep import import_frida
from .injection import Injection, inject

logger = logging.getLogger(__name__)


class FridaNotReadyError(RuntimeError):
    """frida-server on the target serial did not answer within the timeout."""


class FridaClient:
    """A connected frida device, bound to one adb serial, that injects scripts.

    Args:
        device: The connected ``frida.core.Device`` this client wraps.
        frida: The imported frida module, held for its exception types.

    Design:
        Thin over ``frida.core.Device``: it exposes the raw device for callers
        who want frida's full surface, and an ``inject`` shortcut for the common
        attach/spawn-then-load-a-script path. It is built by ``frida_client``,
        which is where the connection and the readiness wait live.
    """

    def __init__(self, device, frida):
        self._device = device
        self._frida = frida

    @property
    def device(self):
        """The underlying connected ``frida.core.Device``."""
        return self._device

    def inject(
        self,
        target: int | str,
        source: str,
        *,
        spawn: bool = False,
        on_message: Callable | None = None,
    ) -> Injection:
        """Attach to or spawn a target on this device and load a script into it.

        See ``gunkata.frida.injection.inject`` for the full contract; this binds
        it to this client's device.
        """
        return inject(
            self._device, target, source, spawn=spawn, on_message=on_message
        )


def frida_client(serial: str, timeout: float = 10.0, poll: float = 0.25) -> FridaClient:
    """Connect to the frida-server on one adb serial, once it answers.

    Args:
        serial: The adb serial; a frida USB device's ``id`` equals its adb
            serial, so this binds to the same transport gunkata selected.
        timeout: Seconds to wait for both the device to appear and its server to
            answer.
        poll: Seconds between server-readiness probes.

    Returns:
        A ``FridaClient`` whose server has answered at least one request.

    Raises:
        FridaUnavailableError: frida is not installed.
        FridaNotReadyError: The server did not answer within ``timeout``.

    Design:
        ``get_device(serial)``, not ``get_usb_device()``: the latter picks the
        first USB device and would misbind when several are attached, so it must
        be the one serial gunkata chose. ``get_device``'s own timeout waits for
        the device to appear; server readiness is separate -- the adb transport
        is present at once, the frida-server port is not -- so a cheap RPC is
        polled past the not-yet-listening race, and a serial-named refusal is
        raised on timeout with the last frida error as its cause.
    """
    frida = import_frida()
    manager = frida.get_device_manager()
    device = manager.get_device(serial, timeout=timeout)
    deadline = time.monotonic() + timeout
    last = None
    while True:
        try:
            device.query_system_parameters()
            return FridaClient(device, frida)
        except frida.Error as exc:
            last = exc
        if time.monotonic() >= deadline:
            raise FridaNotReadyError(
                f"frida-server on {serial!r} did not answer within {timeout}s"
            ) from last
        time.sleep(poll)
