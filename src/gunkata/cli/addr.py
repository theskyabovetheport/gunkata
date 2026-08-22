"""`gunkata addr`: annotate a process's /proc/<pid>/maps listing at one address."""

import sys

import typer

from gunkata.addr import AddrLocator
from gunkata.cli.app import app
from gunkata.cli.completion import complete_process_name
from gunkata.cli.hexaddr import parse_hex_address_expr
from gunkata.cli.tty import stdin_is_tty
from gunkata.device import Device
from gunkata.procmaps import AmbiguousProcessError, NoSuchProcessError, ProcMaps


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
    pid: int = typer.Option(None, "-p", help="Target this pid."),
    name: str = typer.Option(
        None,
        "-P",
        help="Target the sole process matching this name.",
        autocompletion=complete_process_name,
    ),
) -> None:
    """Annotate a process's /proc/<pid>/maps listing at one address.

    Target the process with -p or -P, or pipe a listing on stdin -- e.g.
    from `gunkata procmaps`:

      gunkata addr 0x7fffc274f000+0x1000 -P <name>
      gunkata procmaps -P <name> | gunkata addr 0x7fffc274f000+0x1000
    """
    if pid is not None and name is not None:
        typer.echo("pass at most one of -p/-P", err=True)
        raise typer.Exit(2)
    if pid is None and name is None and stdin_is_tty():
        typer.echo(
            "pass -p or -P, or pipe a /proc/<pid>/maps listing on stdin, e.g.:\n"
            "  gunkata procmaps -P <name> | gunkata addr <address>",
            err=True,
        )
        raise typer.Exit(1)
    try:
        target = parse_hex_address_expr(address)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    if pid is not None or name is not None:
        shell = Device().shell()
        try:
            procmaps = (
                ProcMaps.by_pid(shell, pid)
                if pid is not None
                else ProcMaps.by_name(shell, name)
            )
        except (NoSuchProcessError, AmbiguousProcessError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from None
    else:
        procmaps = ProcMaps(sys.stdin.buffer.read())
    try:
        locator = AddrLocator(procmaps)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    locator.locate(target)
    typer.echo(locator.annotated(before=before, after=after), nl=False)
