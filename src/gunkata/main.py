"""Command-line surface for gunkata, built on Typer. Presentation only; logic lives in gunkata.core."""

import json
import os
import tempfile
import time
from importlib.metadata import version as _pkg_version
from pathlib import Path

import typer

from gunkata.adb import Adb, AdbError
from gunkata.device import Device
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


def _complete_remote_path(ctx, args, incomplete: str) -> list[str]:
    try:
        slash = incomplete.rfind("/")
        if slash == -1:
            dirname, prefix = "", ""
        elif slash == 0:
            dirname, prefix = "/", "/"
        else:
            dirname, prefix = incomplete[:slash], incomplete[: slash + 1]

        serial = _completion_cache_get("serial")
        if serial is None:
            serial = Adb().serial
            _completion_cache_set("serial", serial)
        adb = Adb(serial)

        user = _completion_cache_get("user")
        if user is None:
            user = "root" if Device(adb).has_su else "shell"
            _completion_cache_set("user", user)

        ls_key = f"ls:{dirname or '.'}"
        output = _completion_cache_get(ls_key)
        if output is None:
            listing = Shell(adb, user=user, su_binary="su")(f"ls -1p {dirname or '.'}")
            if not listing.ok:
                return []
            output = listing.stdout
            _completion_cache_set(ls_key, output)

        return [f"{prefix}{name}" for name in output.splitlines() if name]
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
    target = Device(Adb())
    cd = f"cd '{directory}' && " if directory else ""
    if command:
        result = target.shell(user=user)(f"{cd}{' '.join(command)}")
        typer.echo(result.output, nl=False)
        raise typer.Exit(result.rc)
    resolved_user = user if user is not None else ("root" if target.has_su else "shell")
    if directory:
        os.execvp(
            "adb",
            [
                "adb",
                "-s",
                target.serial,
                "shell",
                "-t",
                "su",
                resolved_user,
                "sh",
                "-c",
                f"'{cd}exec sh'",
            ],
        )
    os.execvp("adb", ["adb", "-s", target.serial, "shell", "-t", "su", resolved_user])


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
