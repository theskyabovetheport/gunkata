"""`gunkata shell`: run a one-shot command via su, or attach interactively."""

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.device import Device

_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.command(context_settings=_PASSTHROUGH)
def shell(
    command: list[str] = typer.Argument(None, autocompletion=complete_remote_path),
    directory: str = typer.Option(None, "-C", help="Start the shell in this directory."),
    user: str = typer.Option(
        None, "-U", help="Run as this user, via su (default: root if su is available, else shell)."
    ),
) -> None:
    """Shell via su. With a command, run it and exit; with none, attach interactively."""
    device_shell = Device(Adb()).shell(user=user)
    if command:
        cd = f"cd '{directory}' && " if directory else ""
        result = device_shell(f"{cd}{' '.join(command)}")
        typer.echo(result.output, nl=False)
        raise typer.Exit(result.rc)
    device_shell.execvp_sh(directory)
