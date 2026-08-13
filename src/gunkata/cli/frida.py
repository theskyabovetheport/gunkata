"""`gunkata frida start`/`stop`/`status`: provision and run frida-server on the device."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.device import Device
from gunkata.frida.repo import server_repo
from gunkata.frida.server import FridaServer, FridaServerError

frida_app = typer.Typer(
    no_args_is_help=True, help="Provision and run frida-server on the device."
)
app.add_typer(frida_app, name="frida")


def _frida_server(port: int | None = None, version: str | None = None) -> FridaServer:
    """Build a FridaServer for the sole attached device (composition root)."""
    target = Device(Adb())
    if port is None:
        return target.frida_server(server_repo(), version=version)
    return target.frida_server(server_repo(), version=version, port=port)


@frida_app.command("start")
def frida_start(
    port: int = typer.Option(None, "-p", "--port", help="Loopback port to bind."),
    version: str = typer.Option(
        None, "--version", help="frida version to provision (default: installed frida)."
    ),
) -> None:
    """Launch frida-server detached; it survives this command.

    Raises:
        typer.Exit: the device has no su, or the server did not come up
            within its start timeout.
    """
    try:
        pids = _frida_server(port=port, version=version).start()
    except FridaServerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(f"running (pid {' '.join(str(p) for p in pids)})")


@frida_app.command("stop")
def frida_stop() -> None:
    """Kill any running frida-server. No-op when none is running.

    Raises:
        typer.Exit: the device has no su.
    """
    try:
        killed = _frida_server().stop()
    except FridaServerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if killed:
        typer.echo(f"stopped (pid {' '.join(str(p) for p in killed)})")
    else:
        typer.echo("not running")


@frida_app.command("status")
def frida_status() -> None:
    """Report whether frida-server is running; exit 1 when stopped.

    Raises:
        typer.Exit: the device has no su (exit 1 with a message), or
            frida-server is not running (bare exit 1).
    """
    try:
        pids = _frida_server().running_pids()
    except FridaServerError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if not pids:
        typer.echo("stopped")
        raise typer.Exit(1)
    typer.echo(f"running (pid {' '.join(str(p) for p in pids)})")
