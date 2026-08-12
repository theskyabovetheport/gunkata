"""`gunkata procmaps`: print /proc/<pid>/maps, resolved by pid, name, or fzf pick."""

import sys

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.cli.completion import complete_process_name
from gunkata.cli.fzf import fzf_pick_pid
from gunkata.cli.tty import stdout_is_tty
from gunkata.device import Device
from gunkata.procmaps import AmbiguousProcessError, NoSuchProcessError


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
    """Print /proc/<pid>/maps to stdout.

    With neither -p nor -P, fuzzy-pick the process via fzf -- only when
    stdout is a terminal; maps content and fzf's own picker would otherwise
    both fight over whatever stdout was redirected to.

    Raises:
        typer.Exit: Both -p and -P were given; -P matched zero or more than
            one process; the resolved pid has no /proc entry; or neither was
            given and stdout is not a tty, fzf is missing, or the picker was
            exited without a pick.
    """
    if pid is not None and name is not None:
        typer.echo("pass at most one of -p/-P", err=True)
        raise typer.Exit(2)
    device = Device(Adb())
    if pid is None and name is None:
        if not stdout_is_tty():
            typer.echo(
                "refusing to fuzzy-pick a process: stdout is not a tty; pass -p or -P",
                err=True,
            )
            raise typer.Exit(2)
        pid = fzf_pick_pid(device.ps().entries())
        if pid is None:
            raise typer.Exit(1)
    procmaps_ = device.procmaps()
    try:
        maps = procmaps_.by_pid(pid) if pid is not None else procmaps_.by_name(name)
    except (NoSuchProcessError, AmbiguousProcessError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    sys.stdout.buffer.write(maps)
