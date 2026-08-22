"""`gunkata push`: push a local file to the device."""

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.device import Device


@app.command()
def push(
    lpath: str = typer.Argument(...),
    dpath: str = typer.Argument(
        ...,
        help="Device path to write; a directory receives the file under its local basename.",
        autocompletion=complete_remote_path,
    ),
    inherit_owner: bool = typer.Option(
        True, help="Chown the pushed file to its parent directory's owner."
    ),
) -> None:
    """Push a local file to the device, in adb's LOCAL REMOTE order."""
    Device().shell().push_file(dpath, lpath, inherit_owner=inherit_owner)
