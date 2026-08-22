"""`gunkata pidof`: print the pid(s) of every process matching a name, or fzf-pick one."""

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_process_name
from gunkata.cli.fzf import fzf_pick_pid
from gunkata.device import Device
from gunkata.ps import Ps


@app.command()
def pidof(
    name: str = typer.Argument(None, autocompletion=complete_process_name),
) -> None:
    """Print the pid of every process matching a name, one per line.

    With no name, picks a process interactively with fzf instead.
    """
    device = Device()
    if name is None:
        pid = fzf_pick_pid(Ps(device.shell()).entries())
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
