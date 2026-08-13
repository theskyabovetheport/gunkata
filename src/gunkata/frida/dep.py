"""The single boundary where the optional ``frida`` package is imported."""

from typing import Any


class FridaUnavailableError(RuntimeError):
    """A frida-only code path ran without the frida package installed."""


def import_frida() -> Any:
    """Import the optional frida package, or refuse with an install hint.

    Returns:
        The imported top-level ``frida`` module.

    Raises:
        FridaUnavailableError: frida is not installed; the message names the
            extra to install.

    Design:
        frida ships a large native extension, so it is an optional extra
        (``gunkata[frida]``) imported only where a live client is genuinely
        needed -- the sanctioned function-local import for a heavy dependency.
        Every frida-only path routes through here, so ``import gunkata`` and the
        entire provisioning path stay importable without it, and one message
        names the fix.
    """
    try:
        import frida  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise FridaUnavailableError(
            "frida is not installed; install the optional extra: "
            "pip install 'gunkata[frida]'"
        ) from exc
    return frida
