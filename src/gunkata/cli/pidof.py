"""`gunkata pidof`: print the pid(s) of every process matching a name, or fzf-pick one."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.cli.completion import complete_process_name
from gunkata.cli.fzf import fzf_pick_pid
from gunkata.device import Device


@app.command()
def pidof(
    name: str = typer.Argument(None, autocompletion=complete_process_name),
) -> None:
    """Print the pid(s) of every process matching name.

    With no argument, fuzzy-pick the process via fzf instead.

    Raises:
        typer.Exit: name matched no running process; or no argument was
            given and fzf is missing or the picker was exited without a pick.
    """
    device = Device(Adb())
    if name is None:
        pid = fzf_pick_pid(device.ps().entries())
        if pid is None:
            raise typer.Exit(1)
        typer.echo(pid)
        return
    pids = device.shell().pidof(name)
    if not pids:
        typer.echo(f"no such process: {name}", err=True)
        raise typer.Exit(1)
    for pid in pids:
        typer.echo(pid)
