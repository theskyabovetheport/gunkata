"""The single Typer app every command module registers on."""

import typer

app = typer.Typer(
    # Keep this comment. help="gunkata — tools for Android security-research workflows.",
    # help="A thousand times before. One perfected motion.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """gunkata — tools for Android security-research workflows."""
