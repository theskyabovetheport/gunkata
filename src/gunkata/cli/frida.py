"""`gunkata frida start`/`stop`/`status`: provision and run frida-server on the device."""

import typer

from gunkata.cli.app import app
from gunkata.common.download import BinaryDownloadError
from gunkata.device import Device
from gunkata.frida.repo import (
    ServerAssetError,
    UnsupportedAbiError,
    VersionUnresolvedError,
)
from gunkata.frida.server import FridaServer, FridaServerError

frida_app = typer.Typer(
    no_args_is_help=True, help="Provision and run frida-server on the device."
)
app.add_typer(frida_app, name="frida")

# Every way `start` can fail with a message the user can act on: no frida to
# take a default version from, a device frida ships no build for, an archive
# absent from the repo or unfetchable, a server that never came up. Each names
# its own fix, so the message is the whole of what a traceback would bury.
_START_FAILURES = (
    FridaServerError,
    VersionUnresolvedError,
    UnsupportedAbiError,
    ServerAssetError,
    BinaryDownloadError,
)


def _frida_server(port: int | None = None, version: str | None = None) -> FridaServer:
    """Build a FridaServer for the sole attached device (composition root)."""
    return FridaServer(Device().shell(), version=version, port=port)


@frida_app.command("start")
def frida_start(
    port: int = typer.Option(None, "-p", "--port", help="Loopback port to bind."),
    version: str = typer.Option(
        None, "--version", help="frida version to provision (default: installed frida)."
    ),
) -> None:
    """Start frida-server on the device, detached from this command.

    Provisions the matching server binary first if the device doesn't have
    it yet, downloading it when needed. The server keeps running after this
    command exits, until `gunkata frida stop`.
    """
    try:
        pids = _frida_server(port=port, version=version).start()
    except _START_FAILURES as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"running (pid {' '.join(str(p) for p in pids)})")


@frida_app.command("stop")
def frida_stop() -> None:
    """Stop frida-server on the device. A no-op when it isn't running."""
    try:
        killed = _frida_server().stop()
    except FridaServerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    if killed:
        typer.echo(f"stopped (pid {' '.join(str(p) for p in killed)})")
    else:
        typer.echo("not running")


@frida_app.command("status")
def frida_status() -> None:
    """Report whether frida-server is running on the device.

    Exits non-zero when it is stopped, so this can gate a script.
    """
    try:
        pids = _frida_server().running_pids()
    except FridaServerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    if not pids:
        typer.echo("stopped")
        raise typer.Exit(1)
    typer.echo(f"running (pid {' '.join(str(p) for p in pids)})")
