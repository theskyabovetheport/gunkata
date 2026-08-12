"""`gunkata addr`: annotate a piped /proc/<pid>/maps listing at one address."""

import sys

import typer

from gunkata.addr import AddrLocator
from gunkata.cli.app import app
from gunkata.cli.tty import stdin_is_tty


@app.command()
def addr(
    address: str = typer.Argument(
        ...,
        help="Address to locate, hex terms joined by +/- (e.g. 0x7fffc274f000+0x1000).",
    ),
    after: int = typer.Option(
        3, "-A", min=0, help="Lines of context below (after) the match, like grep -A."
    ),
    before: int = typer.Option(
        3, "-B", min=0, help="Lines of context above (before) the match, like grep -B."
    ),
) -> None:
    """Read a /proc/<pid>/maps listing from stdin; annotate where address falls.

    Raises:
        typer.Exit: address failed to parse as hex terms joined by +/-, or
            stdin is a terminal rather than a piped listing.
    """
    if stdin_is_tty():
        typer.echo(
            "addr reads a /proc/<pid>/maps listing from stdin; pipe one in, e.g.:\n"
            "  gunkata procmaps -P <name> | gunkata addr <address>",
            err=True,
        )
        raise typer.Exit(1)
    try:
        target = AddrLocator.parse_address(address)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    try:
        locator = AddrLocator(sys.stdin.read())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    locator.locate(target)
    typer.echo(locator.annotated(before=before, after=after), nl=False)
