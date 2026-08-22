"""`gunkata mem read`/`gunkata mem write`: process-memory access via /proc/<pid>/mem."""

import sys
from pathlib import Path

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_process_name
from gunkata.cli.hexaddr import parse_hex_address_expr
from gunkata.device import Device
from gunkata.memory import Memory, UnmappedRangeError
from gunkata.procmaps import AmbiguousProcessError, NoSuchProcessError

mem_app = typer.Typer(
    help="Read and write a device process's memory via /proc/<pid>/mem.",
    no_args_is_help=True,
)
app.add_typer(mem_app, name="mem")

_MEM_PID_OPTION = typer.Option(None, "-p", help="Target this pid.")
_MEM_NAME_OPTION = typer.Option(
    None,
    "-P",
    help="Target the sole process matching this name.",
    autocompletion=complete_process_name,
)

def _read_stdin_pid() -> int:
    """Read exactly one pid from stdin, as `gunkata pidof` would produce it.

    Design:
        Requiring exactly one keeps -s/-e unambiguous: they describe a
        single address space, and a name that matched several processes is
        a decision for whoever ran `gunkata pidof`, not something to guess at
        here by looping over every pid it printed.

    Raises:
        typer.Exit: stdin held zero or more than one whitespace-separated
            token, or the token wasn't a valid pid.
    """
    tokens = sys.stdin.read().split()
    if len(tokens) != 1:
        typer.echo(f"expected exactly one pid on stdin, got {len(tokens)}", err=True)
        raise typer.Exit(1)
    try:
        return int(tokens[0])
    except ValueError:
        typer.echo(f"not a valid pid: {tokens[0]!r}", err=True)
        raise typer.Exit(1) from None


def _parse_mem_address_expr(expr: str) -> int:
    """Resolve one of mem's -s/-e expressions, or exit loudly if it fails.

    Raises:
        typer.Exit: expr failed to parse; see parse_hex_address_expr.
    """
    try:
        return parse_hex_address_expr(expr)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None


def _hexdump(data: bytes, base: int) -> str:
    """Render data as offset/hex/ascii rows of 16 bytes each, like xxd's default."""
    lines = []
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + offset:012x}  {hex_part:<47}  {ascii_part}")
    return "\n".join(lines)


def _resolve_mem_pid(device: Device, pid: int | None, name: str | None) -> int:
    """Resolve mem's target pid: -p directly, -P by name, or otherwise stdin.

    Raises:
        typer.Exit: both pid and name were given; name matched zero or more
            than one process; or, with neither given, stdin didn't hold
            exactly one pid.
    """
    if pid is not None and name is not None:
        typer.echo("pass at most one of -p/-P", err=True)
        raise typer.Exit(2)
    if name is not None:
        try:
            pids = device.shell().pidof(name)
            if not pids:
                raise NoSuchProcessError(name)
            if len(pids) > 1:
                raise AmbiguousProcessError(name, pids)
        except (NoSuchProcessError, AmbiguousProcessError) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from None
        return pids[0]
    if pid is not None:
        return pid
    return _read_stdin_pid()


@mem_app.command("read")
def mem_read(
    start: str = typer.Option(..., "-s", help="Start address, e.g. 0x7f0000 or 0x7f0000+0x10."),
    end: str = typer.Option(..., "-e", help="End address (exclusive), same syntax as -s."),
    pid: int = _MEM_PID_OPTION,
    name: str = _MEM_NAME_OPTION,
) -> None:
    """Read a process's memory from -s up to, but not including, -e.

    Target the process with -p or -P; with neither, one pid is read from
    stdin, as `gunkata pidof` prints it.

    Prints a hex dump on a terminal, and writes raw bytes when piped
    elsewhere.
    """
    device = Device()
    target_pid = _resolve_mem_pid(device, pid, name)
    start_addr = _parse_mem_address_expr(start)
    end_addr = _parse_mem_address_expr(end)
    try:
        data = Memory(device.shell(), target_pid).read(start_addr, end_addr)
    except (ValueError, UnmappedRangeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    if sys.stdout.isatty():
        typer.echo(_hexdump(data, start_addr))
    else:
        sys.stdout.buffer.write(data)


@mem_app.command("write")
def mem_write(
    file: Path = typer.Option(..., "-f", help="Local file whose bytes are written."),
    start: str = typer.Option(..., "-s", help="Start address, e.g. 0x7f0000 or 0x7f0000+0x10."),
    end: str = typer.Option(
        None, "-e", help="Upper bound the write must not cross (optional)."
    ),
    pid: int = _MEM_PID_OPTION,
    name: str = _MEM_NAME_OPTION,
) -> None:
    """Write a local file's bytes into a process's memory at -s.

    Target the process with -p or -P; with neither, one pid is read from
    stdin, as `gunkata pidof` prints it.

    With -e, a write that would reach past that address is refused instead
    of truncated.
    """
    device = Device()
    target_pid = _resolve_mem_pid(device, pid, name)
    start_addr = _parse_mem_address_expr(start)
    end_addr = _parse_mem_address_expr(end) if end is not None else None
    data = file.read_bytes()
    try:
        Memory(device.shell(), target_pid).write(start_addr, data, end_addr)
    except (ValueError, UnmappedRangeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
