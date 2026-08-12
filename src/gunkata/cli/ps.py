"""`gunkata ps`: list the device's running processes."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.cli.tty import stdout_is_tty
from gunkata.device import Device


@app.command()
def ps() -> None:
    """List the device's running processes.

    Design:
        Aligned two-column output with a header when stdout is a terminal;
        unaligned "pid name" -- one predictable separator, no column widths
        that shift with the data -- when it's piped elsewhere.
    """
    entries = Device(Adb()).ps().entries()
    if stdout_is_tty():
        pid_width = max([len("PID")] + [len(str(entry.pid)) for entry in entries])
        typer.echo(f"{'PID':<{pid_width}}  NAME")
        for entry in entries:
            typer.echo(f"{entry.pid:<{pid_width}}  {entry.name}")
    else:
        for entry in entries:
            typer.echo(f"{entry.pid} {entry.name}")
