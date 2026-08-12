"""`gunkata version`: print the installed package version."""

from importlib.metadata import version as _pkg_version

import typer

from gunkata.cli.app import app


@app.command()
def version() -> None:
    """Print the installed gunkata version."""
    typer.echo(_pkg_version("gunkata"))
