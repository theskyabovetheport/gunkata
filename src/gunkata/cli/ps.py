"""`gunkata ps`: list the device's running processes."""

import typer

from gunkata.cli.app import app
from gunkata.cli.tty import stdout_is_tty
from gunkata.device import Device
from gunkata.ps import Ps


@app.command()
def ps() -> None:
    """List the device's running processes as PID and NAME.

    Prints an aligned table with a header on a terminal, and plain
    "pid name" lines when piped elsewhere.
    """
    # Piped output stays unaligned on purpose: one predictable separator, and
    # no column widths that shift with the data a reader has to parse.
    entries = Ps(Device().shell()).entries()
    if stdout_is_tty():
        pid_width = max([len("PID")] + [len(str(entry.pid)) for entry in entries])
        typer.echo(f"{'PID':<{pid_width}}  NAME")
        for entry in entries:
            typer.echo(f"{entry.pid:<{pid_width}}  {entry.name}")
    else:
        for entry in entries:
            typer.echo(f"{entry.pid} {entry.name}")
