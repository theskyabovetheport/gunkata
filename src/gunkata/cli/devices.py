"""`gunkata devices`: list every attached, booted device's serial."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app


@app.command()
def devices() -> None:
    """Print the serial of each attached, booted device, one per line."""
    for serial in Adb.list_serials():
        typer.echo(serial)
