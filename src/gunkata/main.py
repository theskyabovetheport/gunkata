"""Command-line surface for gunkata, built on Typer. Presentation only; logic lives in gunkata.core."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version as _pkg_version
from pathlib import Path

import typer

from gunkata.adb import Adb, AdbError
from gunkata.addr import AddrLocator
from gunkata.device import Device
from gunkata.memory import UnmappedRangeError
from gunkata.procmaps import AmbiguousProcessError, NoSuchProcessError
from gunkata.ps import ProcessEntry, Ps
from gunkata.settings import SuBinary
from gunkata.shell import Shell

app = typer.Typer(
    # Keep this comment. help="gunkata — tools for Android security-research workflows.",
    # help="A thousand times before. One perfected motion.",
    no_args_is_help=True,
)

_PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True}


@app.callback()
def _root() -> None:
    """gunkata — tools for Android security-research workflows."""


@app.command()
def version() -> None:
    """Print the installed gunkata version."""
    typer.echo(_pkg_version("gunkata"))


def _stdin_is_tty() -> bool:
    """Whether stdin is a terminal.

    Design:
        A seam for tests: Typer's CliRunner replaces ``sys.stdin`` for the
        duration of an invocation, so a test can't patch the real object
        beforehand and have it take effect -- it patches this function
        instead.
    """
    return sys.stdin.isatty()


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
    if _stdin_is_tty():
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


@app.command()
def device() -> None:
    """Print the sole attached device's serial; print nothing if there isn't exactly one."""
    try:
        typer.echo(Adb().serial)
    except AdbError:
        raise typer.Exit(1)


@app.command()
def devices() -> None:
    """Print the serial of each attached, booted device, one per line."""
    for serial in Adb.list_serials():
        typer.echo(serial)


_COMPLETION_CACHE_TTL = 2.0


def _completion_cache_path() -> Path:
    return Path(tempfile.gettempdir()) / f"gunkata-complete-{os.getuid()}.json"


def _completion_cache_get(key: str) -> str | None:
    try:
        cache = json.loads(_completion_cache_path().read_text())
        entry = cache[key]
        if time.time() - entry["ts"] < _COMPLETION_CACHE_TTL:
            return entry["value"]
    except Exception:
        pass
    return None


def _completion_cache_set(key: str, value: str) -> None:
    try:
        path = _completion_cache_path()
        cache = json.loads(path.read_text()) if path.exists() else {}
        cache[key] = {"value": value, "ts": time.time()}
        path.write_text(json.dumps(cache))
    except Exception:
        pass


def _cached_serial_and_user() -> tuple[Adb, str]:
    """Resolve the sole attached device and its default su user, from cache if fresh.

    Design:
        Shared by every completer: each keystroke re-invokes the CLI as a
        fresh process, so the in-memory cache a long-lived object would give
        for free instead lives in the on-disk completion cache.
    """
    serial = _completion_cache_get("serial")
    if serial is None:
        serial = Adb().serial
        _completion_cache_set("serial", serial)
    adb = Adb(serial)

    user = _completion_cache_get("user")
    if user is None:
        user = "root" if Device(adb).has_su else "shell"
        _completion_cache_set("user", user)
    return adb, user


def _complete_remote_path(ctx, args, incomplete: str) -> list[str]:
    try:
        slash = incomplete.rfind("/")
        if slash == -1:
            dirname, prefix = "", ""
        elif slash == 0:
            dirname, prefix = "/", "/"
        else:
            dirname, prefix = incomplete[:slash], incomplete[: slash + 1]

        adb, user = _cached_serial_and_user()

        ls_key = f"ls:{dirname or '.'}"
        output = _completion_cache_get(ls_key)
        if output is None:
            listing = Shell(adb, user=user, su=SuBinary(name="su"))(
                f"ls -1p {dirname or '.'}"
            )
            if not listing.ok:
                return []
            output = listing.stdout
            _completion_cache_set(ls_key, output)

        return [f"{prefix}{name}" for name in output.splitlines() if name]
    except Exception:
        return []


def _complete_process_name(ctx, args, incomplete: str) -> list[str]:
    try:
        adb, user = _cached_serial_and_user()

        names_cache = _completion_cache_get("ps:names")
        if names_cache is None:
            names = Ps(Shell(adb, user=user, su=SuBinary(name="su"))).names()
            names_cache = "\n".join(names)
            _completion_cache_set("ps:names", names_cache)

        return [name for name in names_cache.splitlines() if name.startswith(incomplete)]
    except Exception:
        return []


@app.command(context_settings=_PASSTHROUGH)
def shell(
    command: list[str] = typer.Argument(None, autocompletion=_complete_remote_path),
    directory: str = typer.Option(
        None, "-C", help="Start the shell in this directory."
    ),
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


@app.command()
def pull(
    dpath: str = typer.Argument(..., autocompletion=_complete_remote_path),
    lpath: str = typer.Argument(...),
    user: str = typer.Option(
        None, "-U", help="Run as this user, via su (default: root if su is available, else shell)."
    ),
) -> None:
    """Pull a file from the device."""
    Device(Adb()).shell(user=user).pull_file(dpath, lpath)


def _stdout_is_tty() -> bool:
    """Whether stdout is a terminal.

    Design:
        A seam for tests: Typer's CliRunner replaces ``sys.stdout`` for the
        duration of an invocation, so a test can't patch the real object
        beforehand and have it take effect -- it patches this function
        instead.
    """
    return sys.stdout.isatty()


@app.command()
def ps() -> None:
    """List the device's running processes.

    Design:
        Aligned two-column output with a header when stdout is a terminal;
        unaligned "pid name" -- one predictable separator, no column widths
        that shift with the data -- when it's piped elsewhere.
    """
    entries = Device(Adb()).ps().entries()
    if _stdout_is_tty():
        pid_width = max([len("PID")] + [len(str(entry.pid)) for entry in entries])
        typer.echo(f"{'PID':<{pid_width}}  NAME")
        for entry in entries:
            typer.echo(f"{entry.pid:<{pid_width}}  {entry.name}")
    else:
        for entry in entries:
            typer.echo(f"{entry.pid} {entry.name}")


def _fzf_pick_pid(entries: list[ProcessEntry]) -> int | None:
    """Let the user fuzzy-pick a process from entries via fzf.

    Returns:
        The picked pid, or None if the user exited fzf without picking one.

    Raises:
        typer.Exit: fzf is not on PATH.

    Design:
        fzf reads the candidate list from stdin but draws its UI straight to
        the controlling terminal, so piping the list in and capturing stdout
        for the pick don't fight over the same channel.
    """
    if shutil.which("fzf") is None:
        typer.echo(
            "fzf is required for interactive process selection; "
            "install it: https://github.com/junegunn/fzf#installation",
            err=True,
        )
        raise typer.Exit(1)
    listing = "\n".join(f"{entry.pid}\t{entry.name}" for entry in entries)
    result = subprocess.run(
        ["fzf"], input=listing, stdout=subprocess.PIPE, text=True
    )
    picked = result.stdout.strip()
    if result.returncode != 0 or not picked:
        return None
    return int(picked.split("\t", 1)[0])


@app.command()
def procmaps(
    pid: int = typer.Option(None, "-p", help="Print maps for this pid."),
    name: str = typer.Option(
        None,
        "-P",
        help="Print maps for the sole process matching this name.",
        autocompletion=_complete_process_name,
    ),
) -> None:
    """Print /proc/<pid>/maps to stdout.

    With neither -p nor -P, fuzzy-pick the process via fzf -- only when
    stdout is a terminal; maps content and fzf's own picker would otherwise
    both fight over whatever stdout was redirected to.

    Raises:
        typer.Exit: Both -p and -P were given; -P matched zero or more than
            one process; the resolved pid has no /proc entry; or neither was
            given and stdout is not a tty, fzf is missing, or the picker was
            exited without a pick.
    """
    if pid is not None and name is not None:
        typer.echo("pass at most one of -p/-P", err=True)
        raise typer.Exit(2)
    device = Device(Adb())
    if pid is None and name is None:
        if not _stdout_is_tty():
            typer.echo(
                "refusing to fuzzy-pick a process: stdout is not a tty; pass -p or -P",
                err=True,
            )
            raise typer.Exit(2)
        pid = _fzf_pick_pid(device.ps().entries())
        if pid is None:
            raise typer.Exit(1)
    procmaps_ = device.procmaps()
    try:
        maps = procmaps_.by_pid(pid) if pid is not None else procmaps_.by_name(name)
    except (NoSuchProcessError, AmbiguousProcessError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    sys.stdout.buffer.write(maps)


@app.command()
def pidof(
    name: str = typer.Argument(None, autocompletion=_complete_process_name),
) -> None:
    """Print the pid(s) of every process matching name.

    With no argument, fuzzy-pick the process via fzf instead.

    Raises:
        typer.Exit: name matched no running process; or no argument was
            given and fzf is missing or the picker was exited without a pick.
    """
    device = Device(Adb())
    if name is None:
        pid = _fzf_pick_pid(device.ps().entries())
        if pid is None:
            raise typer.Exit(1)
        typer.echo(pid)
        return
    pids = device.shell().pidof(name)
    if not pids:
        typer.echo(f"no such process: {name}", err=True)
        raise typer.Exit(1)
    for pid in pids:
        typer.echo(pid)


@app.command()
def push(
    lpath: str = typer.Argument(...),
    dpath: str = typer.Argument(..., autocompletion=_complete_remote_path),
    user: str = typer.Option(
        None, "-U", help="Run as this user, via su (default: root if su is available, else shell)."
    ),
    inherit_owner: bool = typer.Option(
        True, help="Chown the pushed file to its parent directory's owner."
    ),
) -> None:
    """Push a local file to the device, in adb's LOCAL REMOTE order."""
    Device(Adb()).shell(user=user).push_file(dpath, lpath, inherit_owner=inherit_owner)


mem_app = typer.Typer(
    help="Read and write a device process's memory via /proc/<pid>/mem.",
    no_args_is_help=True,
)
app.add_typer(mem_app, name="mem")

_MEM_USER_OPTION = typer.Option(
    None, "-U", help="Run as this user, via su (default: root if su is available, else shell)."
)


def _read_stdin_pid() -> int:
    """Read exactly one pid from stdin, as `gk pidof` would produce it.

    Design:
        Requiring exactly one keeps -s/-e unambiguous: they describe a
        single address space, and a name that matched several processes is
        a decision for whoever ran `gk pidof`, not something to guess at
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
        raise typer.Exit(1)


_MEM_ADDRESS_TERM = re.compile(r"[+-]?[^+-]+")


def _parse_mem_address_expr(expr: str) -> int:
    """Resolve an ADDR{+-}OFFSET{+-}OFFSET... expression to an integer address.

    Args:
        expr: A base address in hex, followed by any number of chained
            +offset/-offset terms, each hex the same way -- e.g. "7f0000",
            "0x7f0000+0x10", "0x7f0000+0x100-0x10". An "0x" prefix is
            accepted but not required, matching the bare hex
            /proc/<pid>/maps prints, so an address copied straight from it
            needs no editing.

    Returns:
        The base address with every chained offset applied in order.

    Raises:
        typer.Exit: expr is empty, or a term isn't a valid hex integer.
    """
    terms = _MEM_ADDRESS_TERM.findall(expr.strip())
    if not terms:
        typer.echo(f"empty address expression: {expr!r}", err=True)
        raise typer.Exit(2)
    try:
        addr = int(terms[0], 16)
        for term in terms[1:]:
            sign = -1 if term[0] == "-" else 1
            addr += sign * int(term[1:] if term[0] in "+-" else term, 16)
    except ValueError as exc:
        typer.echo(f"not a valid address expression {expr!r}: {exc}", err=True)
        raise typer.Exit(2)
    return addr


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
    """Resolve gk mem's target pid: -p directly, -P by name, or otherwise stdin.

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
            raise typer.Exit(1)
        return pids[0]
    if pid is not None:
        return pid
    return _read_stdin_pid()


_MEM_PID_OPTION = typer.Option(None, "-p", help="Target this pid.")
_MEM_NAME_OPTION = typer.Option(
    None,
    "-P",
    help="Target the sole process matching this name.",
    autocompletion=_complete_process_name,
)


@mem_app.command("read")
def mem_read(
    start: str = typer.Option(..., "-s", help="Start address, e.g. 0x7f0000 or 0x7f0000+0x10."),
    end: str = typer.Option(..., "-e", help="End address (exclusive), same syntax as -s."),
    pid: int = _MEM_PID_OPTION,
    name: str = _MEM_NAME_OPTION,
    user: str = _MEM_USER_OPTION,
) -> None:
    """Read [start, end) from a process's memory.

    With neither -p nor -P, the pid comes from stdin.

    Raw bytes go to stdout when it's piped elsewhere; a hex dump when
    stdout is a terminal.

    Raises:
        typer.Exit: both -p and -P were given; -P matched zero or more than
            one process; neither was given and stdin didn't hold exactly one
            pid; -s/-e failed to parse; or the resolved range isn't fully
            mapped in the process.
    """
    device = Device(Adb())
    target_pid = _resolve_mem_pid(device, pid, name)
    start_addr = _parse_mem_address_expr(start)
    end_addr = _parse_mem_address_expr(end)
    try:
        data = device.memory(target_pid, user=user).read(start_addr, end_addr)
    except (ValueError, UnmappedRangeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
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
    user: str = _MEM_USER_OPTION,
) -> None:
    """Write file's bytes into a process's memory at start.

    With neither -p nor -P, the pid comes from stdin.

    Raises:
        typer.Exit: both -p and -P were given; -P matched zero or more than
            one process; neither was given and stdin didn't hold exactly one
            pid; -s/-e failed to parse; the write would cross the given -e;
            or the resolved range isn't fully mapped in the process.
    """
    device = Device(Adb())
    target_pid = _resolve_mem_pid(device, pid, name)
    start_addr = _parse_mem_address_expr(start)
    end_addr = _parse_mem_address_expr(end) if end is not None else None
    data = file.read_bytes()
    try:
        device.memory(target_pid, user=user).write(start_addr, data, end_addr)
    except (ValueError, UnmappedRangeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)


def main() -> None:
    """Entry point for the ``gunkata`` console script."""
    app()
