"""`gunkata push`: push a local file to the device."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.device import Device


@app.command()
def push(
    lpath: str = typer.Argument(...),
    dpath: str = typer.Argument(..., autocompletion=complete_remote_path),
    user: str = typer.Option(
        None, "-U", help="Run as this user, via su (default: root if su is available, else shell)."
    ),
    inherit_owner: bool = typer.Option(
        True, help="Chown the pushed file to its parent directory's owner."
    ),
) -> None:
    """Push a local file to the device, in adb's LOCAL REMOTE order."""
    Device(Adb()).shell(user=user).push_file(dpath, lpath, inherit_owner=inherit_owner)
