"""`gunkata device`: print the sole attached device's serial."""

import typer

from gunkata.adb import Adb, AdbError
from gunkata.cli.app import app


@app.command()
def device() -> None:
    """Print the sole attached device's serial; print nothing if there isn't exactly one."""
    try:
        typer.echo(Adb().serial)
    except AdbError:
        raise typer.Exit(1)
