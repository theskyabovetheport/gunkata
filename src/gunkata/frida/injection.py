"""Attaching or spawning a target and loading a Frida script, with cleanup."""

import logging
from collections.abc import Callable

from .dep import import_frida

logger = logging.getLogger(__name__)

_CONSOLE_LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


class Injection:
    """A loaded Frida script and its session, released together.

    Args:
        frida: The imported frida module, held for its exception types.
        device: The connected frida device the target runs on.
        session: The attached session.
        script: The loaded script.
        pid: The pid frida spawned, or None when attaching. A spawn is left
            suspended until ``resume``; closing without resuming kills it.

    Design:
        A context manager over frida.core's own Session/Script for deterministic
        teardown. frida.core already exposes spawn/attach/create_script/load;
        this only sequences them and guarantees release, adding no policy.
    """

    def __init__(self, frida, device, session, script, pid: int | None):
        self._frida = frida
        self._device = device
        self._session = session
        self._script = script
        self._pid = pid
        self._resumed = False
        self._closed = False

    def __enter__(self) -> "Injection":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def resume(self) -> None:
        """Resume a spawned target that has been suspended since spawn.

        Raises:
            InvalidOperationError: The target was attached, not spawned, so there
                is nothing suspended to resume.
        """
        if self._pid is None:
            raise self._frida.InvalidOperationError(
                "target was attached, not spawned"
            )
        self._device.resume(self._pid)
        self._resumed = True

    def close(self) -> None:
        """Unload the script, detach the session, and kill a suspended spawn.

        Design:
            Idempotent, and each step is guarded on its own so a later step still
            runs when an earlier one fails. It swallows frida errors from a target
            that already died, because a dead target is the state close() is
            trying to reach; the failure is logged with the pid for context.
        """
        if self._closed:
            return
        self._closed = True
        steps = (self._script.unload, self._session.detach, self._kill_if_suspended)
        for step in steps:
            try:
                step()
            except self._frida.Error:
                logger.warning("frida teardown step failed", extra={"pid": self._pid})

    def _kill_if_suspended(self) -> None:
        if self._pid is not None and not self._resumed:
            self._device.kill(self._pid)


def inject(
    device,
    target: int | str,
    source: str,
    *,
    spawn: bool = False,
    on_message: Callable | None = None,
) -> Injection:
    """Attach to or spawn a target, load a JS script into it, ready to run.

    Args:
        device: A connected frida device (see FridaClient / frida_client).
        target: A pid or process name to attach to, or the program to spawn when
            ``spawn`` is set.
        source: The Frida JavaScript to load.
        spawn: Start ``target`` suspended and inject before its first
            instruction; the caller resumes through the returned handle.
        on_message: Called with frida's native ``(message, data)`` for each
            script ``send()``; None installs no handler.

    Returns:
        A context-managed handle owning the loaded script and session. On a spawn
        the target is suspended until the handle's ``resume``.

    Raises:
        FridaUnavailableError: frida is not installed.
        ProcessNotFoundError: target names no running process (attach mode).
        ExecutableNotFoundError: target names no program to spawn (spawn mode).

    Design:
        Thin over frida.core: it orders spawn/attach -> create_script -> handlers
        -> load, and pairs the result with guaranteed teardown. The script's
        ``console.*`` output is routed to this module's logger; ``on_message`` is
        left for ``send()`` alone, since frida delivers a console line to both
        sinks and handling it in both would log it twice.
    """
    frida = import_frida()
    if spawn:
        pid = device.spawn(target)
        session = device.attach(pid)
    else:
        pid = None
        session = device.attach(target)
    script = session.create_script(source)
    script.set_log_handler(_log_console)
    if on_message is not None:
        script.on("message", on_message)
    script.load()
    return Injection(frida, device, session, script, pid)


def _log_console(level: str, text: str) -> None:
    """Route a Frida ``console.*`` line to this module's logger.

    Args:
        level: frida's console level -- ``info``, ``warning``, or ``error``.
        text: The console text, logged as the message itself: it is human-facing
            script output being relayed, not a gunkata event, so it does not go
            through the structured ``extra=`` discipline gunkata's own events do.
    """
    logger.log(_CONSOLE_LEVELS.get(level, logging.INFO), text)
