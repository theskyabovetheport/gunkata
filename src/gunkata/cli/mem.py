"""`gunkata mem read`/`gunkata mem write`: process-memory access via /proc/<pid>/mem."""

import sys

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


def _resolve_name_to_pid(device: Device, name: str) -> int:
    """Resolve -P's process name to the pid of its sole match.

    Raises:
        typer.Exit: name matched zero or more than one process.
    """
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


def _resolve_mem_pid(device: Device, pid: int | None, name: str | None) -> int:
    """Resolve mem's target pid: exactly one of -p directly or -P by name.

    Raises:
        typer.Exit: neither or both of pid and name were given; name matched
            zero or more than one process.
    """
    if pid is not None and name is not None:
        typer.echo("pass exactly one of -p/-P", err=True)
        raise typer.Exit(2)
    if name is not None:
        return _resolve_name_to_pid(device, name)
    if pid is not None:
        return pid
    typer.echo("pass exactly one of -p/-P", err=True)
    raise typer.Exit(2)


@mem_app.command("read")
def mem_read(
    start: str = typer.Option(..., "-s", help="Start address, e.g. 0x7f0000 or 0x7f0000+0x10."),
    end: str = typer.Option(..., "-e", help="End address (exclusive), same syntax as -s."),
    pid: int = _MEM_PID_OPTION,
    name: str = _MEM_NAME_OPTION,
) -> None:
    """Read a process's memory from -s up to, but not including, -e.

    Target the process with exactly one of -p or -P.

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
    start: str = typer.Option(..., "-s", help="Start address, e.g. 0x7f0000 or 0x7f0000+0x10."),
    end: str = typer.Option(
        None, "-e", help="Upper bound the write must not cross (optional)."
    ),
    pid: int = _MEM_PID_OPTION,
    name: str = _MEM_NAME_OPTION,
) -> None:
    """Write stdin's bytes into a process's memory at -s.

    Target the process with exactly one of -p or -P.

    With -e, a write that would reach past that address is refused instead
    of truncated.
    """
    device = Device()
    target_pid = _resolve_mem_pid(device, pid, name)
    start_addr = _parse_mem_address_expr(start)
    end_addr = _parse_mem_address_expr(end) if end is not None else None
    data = sys.stdin.buffer.read()
    try:
        Memory(device.shell(), target_pid).write(start_addr, data, end_addr)
    except (ValueError, UnmappedRangeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
