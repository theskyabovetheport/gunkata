"""Command-line surface for gunkata, built on Typer. Presentation only; logic lives in gunkata.core."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.metadata import version as _pkg_version
from pathlib import Path

import typer

from gunkata.adb import Adb, AdbError
from gunkata.device import Device
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


@app.command()
def ps() -> None:
    """List the device's running processes.

    Design:
        Aligned two-column output with a header when stdout is a terminal;
        unaligned "pid name" -- one predictable separator, no column widths
        that shift with the data -- when it's piped elsewhere.
    """
    entries = Device(Adb()).ps().entries()
    if sys.stdout.isatty():
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

    With neither -p nor -P, fuzzy-pick the process via fzf.

    Raises:
        typer.Exit: Both -p and -P were given; -P matched zero or more than
            one process; the resolved pid has no /proc entry; or neither was
            given and fzf is missing or the picker was exited without a pick.
    """
    if pid is not None and name is not None:
        typer.echo("pass at most one of -p/-P", err=True)
        raise typer.Exit(2)
    device = Device(Adb())
    if pid is None and name is None:
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


def main() -> None:
    """Entry point for the ``gunkata`` console script."""
    app()
