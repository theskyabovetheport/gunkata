"""`gunkata pull`: pull a file, a directory, or a wildcard's matches from the device."""

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.device import Device
from gunkata.shell import ShellError


@app.command()
def pull(
    dpath: str = typer.Argument(..., autocompletion=complete_remote_path),
    lpath: str = typer.Argument(
        None,
        help="Local destination (default: the current directory). A plain file"
        " lands there under its own name, or under its remote basename if lpath"
        " names an existing local directory. A wildcard or a directory always"
        " treats lpath as a directory to land in or under, even when lpath"
        " looks like a filename.",
    ),
) -> None:
    """Pull a file, a directory, or a wildcard's matches from the device."""
    try:
        result = Device().shell().pull(dpath, lpath)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    except ShellError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    if result.skipped:
        typer.echo(f"skipped {len(result.skipped)}: {', '.join(result.skipped)}", err=True)
    for path in result.paths:
        typer.echo(path)
