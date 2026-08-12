"""`gunkata pull`: pull a file from the device."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.device import Device


@app.command()
def pull(
    dpath: str = typer.Argument(..., autocompletion=complete_remote_path),
    lpath: str = typer.Argument(...),
    user: str = typer.Option(
        None, "-U", help="Run as this user, via su (default: root if su is available, else shell)."
    ),
) -> None:
    """Pull a file from the device."""
    Device(Adb()).shell(user=user).pull_file(dpath, lpath)
