"""`gunkata addr`: annotate a piped /proc/<pid>/maps listing at one address."""

import sys

import typer

from gunkata.addr import AddrLocator
from gunkata.cli.app import app
from gunkata.cli.hexaddr import parse_hex_address_expr
from gunkata.cli.tty import stdin_is_tty
from gunkata.procmaps import ProcMaps


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
    """Annotate a piped /proc/<pid>/maps listing at one address.

    Reads the listing from stdin and marks the mapping the address falls
    in, with surrounding lines for context:

      gunkata procmaps -P <name> | gunkata addr 0x7fffc274f000+0x1000
    """
    if stdin_is_tty():
        typer.echo(
            "addr reads a /proc/<pid>/maps listing from stdin; pipe one in, e.g.:\n"
            "  gunkata procmaps -P <name> | gunkata addr <address>",
            err=True,
        )
        raise typer.Exit(1)
    try:
        target = parse_hex_address_expr(address)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    try:
        procmaps = ProcMaps(sys.stdin.buffer.read())
        locator = AddrLocator(procmaps)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    locator.locate(target)
    typer.echo(locator.annotated(before=before, after=after), nl=False)
