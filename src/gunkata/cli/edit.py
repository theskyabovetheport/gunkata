"""`gunkata edit`: edit a device file through a local editor, sudoedit-style."""

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.device import Device
from gunkata.edit import Edit, EditorNotFoundError


@app.command()
def edit(
    dpath: str = typer.Argument(..., autocompletion=complete_remote_path),
    editor: str = typer.Option(
        None, "--editor", help="Editor to launch (default: $VISUAL, then $EDITOR)."
    ),
) -> None:
    """Edit a device file locally: pull it, run your editor, push it back if changed."""
    try:
        changed = Edit(Device().shell(), editor=editor).run(dpath)
    except EditorNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    typer.echo(f"{dpath}: {'updated' if changed else 'unchanged'}")
