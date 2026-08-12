"""Shell-completion helpers: an on-disk cache, and the completers built on it.

Design:
    Shared by every completer: each keystroke re-invokes the CLI as a fresh
    process, so the in-memory cache a long-lived object would give for free
    instead lives in a per-uid file in the system temp dir, with a short TTL
    so a stale device or process list doesn't linger past its usefulness.
"""

import json
import os
import tempfile
import time
from pathlib import Path

# typer vendors click as typer._click and doesn't re-export CompletionItem
# publicly; this is the only path to it given the project depends on typer
# alone, not click.
from typer._click.shell_completion import CompletionItem

from gunkata.adb import Adb
from gunkata.device import Device
from gunkata.ps import Ps
from gunkata.settings import SuBinary
from gunkata.shell import Shell

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
    """Resolve the sole attached device and its default su user, from cache if fresh."""
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


def complete_remote_path(ctx, args, incomplete: str) -> list[CompletionItem]:
    """Complete a remote path against `ls -1p` of its containing directory.

    Design:
        Candidates carry type="dir"/"file", not bare strings: the shell
        completion scripts Typer/Click generate use that marker to skip the
        trailing space they'd otherwise insert after a completed value, which
        is what lets a directory completion (already ending in "/") be
        tabbed into further instead of ending the argument.
    """
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

        return [
            CompletionItem(f"{prefix}{name}", type="dir" if name.endswith("/") else "file")
            for name in output.splitlines()
            if name
        ]
    except Exception:
        return []


def complete_process_name(ctx, args, incomplete: str) -> list[str]:
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
