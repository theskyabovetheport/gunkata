"""`gunkata procmaps`: print /proc/<pid>/maps, resolved by pid, name, or fzf pick."""

import sys

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_process_name
from gunkata.cli.fzf import fzf_pick_pid
from gunkata.cli.tty import stdout_is_tty
from gunkata.device import Device
from gunkata.procmaps import AmbiguousProcessError, NoSuchProcessError, ProcMaps
from gunkata.ps import Ps


@app.command()
def procmaps(
    pid: int = typer.Option(None, "-p", help="Print maps for this pid."),
    name: str = typer.Option(
        None,
        "-P",
        help="Print maps for the sole process matching this name.",
        autocompletion=complete_process_name,
    ),
) -> None:
    """Print a process's memory map, as the device's own /proc reports it.

    Target the process with -p or -P; with neither, picks one interactively
    with fzf, which needs a terminal on stdout.
    """
    if pid is not None and name is not None:
        typer.echo("pass at most one of -p/-P", err=True)
        raise typer.Exit(2)
    device = Device()
    if pid is None and name is None:
        # fzf draws its picker on stdout, so a redirected stdout would have the
        # picker and the maps content fighting over the same destination.
        if not stdout_is_tty():
            typer.echo(
                "refusing to fuzzy-pick a process: stdout is not a tty; pass -p or -P",
                err=True,
            )
            raise typer.Exit(2)
        pid = fzf_pick_pid(Ps(device.shell()).entries())
        if pid is None:
            raise typer.Exit(1)
    shell = device.shell()
    try:
        maps = (
            ProcMaps.by_pid(shell, pid)
            if pid is not None
            else ProcMaps.by_name(shell, name)
        )
    except (NoSuchProcessError, AmbiguousProcessError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    sys.stdout.buffer.write(maps.raw)
