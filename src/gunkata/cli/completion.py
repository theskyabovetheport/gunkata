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

from gunkata.device import Device
from gunkata.ps import Ps
from gunkata.shell import Shell

_COMPLETION_CACHE_TTL = 2.0


def _completion_cache_path() -> Path:
    return Path(tempfile.gettempdir()) / f"gunkata-complete-{os.getuid()}.json"


def _completion_cache_get(key: str) -> str | None:
    # Resilience boundary: the cache is a pure optimization, so a missing
    # file, corrupt JSON, or a stale schema must read as a cache miss, never
    # crash the completer. Not logged: this runs inside a live shell's
    # tab-completion, where stray stderr output corrupts what the user sees.
    try:
        cache = json.loads(_completion_cache_path().read_text())
        entry = cache[key]
        if time.time() - entry["ts"] < _COMPLETION_CACHE_TTL:
            return entry["value"]
    except Exception:  # noqa: BLE001
        pass
    return None


def _completion_cache_set(key: str, value: str) -> None:
    # Resilience boundary, same reasoning as _completion_cache_get: a write
    # failure (permissions, disk full, a racing writer) must not surface --
    # losing the cache costs a slower completion, not a broken one.
    try:
        path = _completion_cache_path()
        cache = json.loads(path.read_text()) if path.exists() else {}
        cache[key] = {"value": value, "ts": time.time()}
        path.write_text(json.dumps(cache))
    except Exception:  # noqa: BLE001
        pass


def _cached_shell() -> Shell:
    """Build a shell on the target device, taking its serial from cache if fresh.

    Returns:
        A shell wrapped exactly as the commands being completed will wrap
        theirs -- same device, same su settings -- so a completion listing is
        never produced as a user the completed command couldn't run as.

    Design:
        Built through Device rather than Shell directly, because that is what
        applies the device's persisted settings; a completer that skipped it
        would list /data/data as "shell" and come back empty against a device
        configured for root.
    """
    serial = _completion_cache_get("serial")
    if serial is None:
        serial = Device().serial
        _completion_cache_set("serial", serial)
    return Device(serial).shell()


def complete_remote_path(ctx, args, incomplete: str) -> list[tuple[str, str]]:
    """Complete a remote path against `ls -1p` of its containing directory.

    Returns:
        (value, help) pairs, help naming "dir" or "file".

    Design:
        typer's autocompletion= accepts a str or a (value, help) tuple; its
        shell_complete= slot instead expects a CompletionItem, whose .type
        field could mark dir vs file. But typer's own bash/zsh/fish/
        powershell renderers only ever read a CompletionItem's .value/.help,
        never .type, so a dir/file marker never reaches the shell either
        way. Carrying it as help text costs nothing and needs no private
        import -- CompletionItem has no public path in typer's API -- while
        shell_complete= is flagged for removal by typer's own deprecation
        warning.
    """
    try:
        slash = incomplete.rfind("/")
        if slash == -1:
            dirname, prefix = "", ""
        elif slash == 0:
            dirname, prefix = "/", "/"
        else:
            dirname, prefix = incomplete[:slash], incomplete[: slash + 1]

        ls_key = f"ls:{dirname or '.'}"
        output = _completion_cache_get(ls_key)
        if output is None:
            listing = _cached_shell()(f"ls -1p {dirname or '.'}")
            if not listing.ok:
                return []
            output = listing.stdout
            _completion_cache_set(ls_key, output)

        return [
            (f"{prefix}{name}", "dir" if name.endswith("/") else "file")
            for name in output.splitlines()
            if name
        ]
    # Resilience boundary: no device, a broken shell, or a stale cache entry
    # must offer no completions, never crash the user's shell. Not logged --
    # see _completion_cache_get.
    except Exception:  # noqa: BLE001
        return []


def complete_process_name(ctx, args, incomplete: str) -> list[str]:
    try:
        names_cache = _completion_cache_get("ps:names")
        if names_cache is None:
            names = Ps(_cached_shell()).names()
            names_cache = "\n".join(names)
            _completion_cache_set("ps:names", names_cache)

        return [name for name in names_cache.splitlines() if name.startswith(incomplete)]
    # Resilience boundary, same reasoning as complete_remote_path above.
    except Exception:  # noqa: BLE001
        return []


# --- dir-aware Bash/Zsh completion -----------------------------------------
#
# Workaround, not a design: typer 0.27's own BashComplete/ZshComplete only
# ever render a CompletionItem's .value, never its .help (see
# complete_remote_path's Design note above) -- so the "dir"/"file" marker
# it carries never reaches the shell, and every candidate gets the same
# trailing space, directory or not. That blocks a second Tab from
# continuing into a completed directory without first deleting the space.
# This block makes typer act on that marker by overriding just enough of
# its private shell-script generation to do so. Remove it, and the patch
# call at the bottom, once typer reads .help (or .type) itself.

import typer._completion_classes as _typer_completion_classes  # noqa: E402
from typer._click.shell_completion import add_completion_class  # noqa: E402
from typer._completion_classes import BashComplete, ZshComplete  # noqa: E402

_NOSPACE_BASH_SOURCE_TEMPLATE = """\
%(complete_func)s() {
    local response
    response=$(env COMP_WORDS="${COMP_WORDS[*]}" \\
                    COMP_CWORD=$COMP_CWORD \\
                    %(autocomplete_var)s=complete_bash "$1")

    COMPREPLY=()
    local all_dirs=1
    local kind value
    while IFS=$'\\t' read -r kind value; do
        [[ -z "$value" ]] && continue
        COMPREPLY+=("$value")
        [[ "$kind" == "dir" ]] || all_dirs=0
    done <<< "$response"

    if [[ ${#COMPREPLY[@]} -eq 1 && $all_dirs -eq 1 ]]; then
        compopt -o nospace
    fi
    return 0
}

complete -o default -F %(complete_func)s %(prog_name)s
"""


class _NoSpaceBashComplete(BashComplete):
    """BashComplete whose generated function skips the trailing space after
    a single unambiguous directory match, so a second Tab continues into it.

    Design:
        Encodes "help\\tvalue" per line instead of typer's bare value, and
        the bash function above parses that back out: bash's `compopt -o
        nospace` only takes effect for the single-unambiguous-match case (a
        menu of several candidates has no per-item space control), so it's
        called only when there is exactly one candidate and its help names
        a directory.
    """

    source_template = _NOSPACE_BASH_SOURCE_TEMPLATE

    def format_completion(self, item) -> str:
        return f"{item.help or ''}\t{item.value}"


def _zsh_compadd_script(completions) -> str:
    """Build the `compadd` calls a zsh completion widget should `eval`.

    Returns:
        A `;`-joined sequence of `compadd` invocations, one per candidate,
        in the order `completions` was given -- the caller handles an empty
        list. A directory candidate's call carries `-S ''` so zsh skips the
        trailing space its default suffix would otherwise add; every other
        call keeps that default.

    Design:
        One call per item, not one call per type: `compadd -S '' -- dir1
        dir2` followed by `compadd -- file1` would put every directory
        before every file regardless of name, silently undoing the
        alphabetical order `ls -1p` already gave complete_remote_path's
        candidates. Split out from ZshComplete.complete() so it can be
        unit-tested without needing a real click Context/env-var completion
        round trip.
    """

    def quote(value: str) -> str:
        return "'" + value.replace("'", "'\\''") + "'"

    def call(item) -> str:
        suffix = " -S ''" if item.help == "dir" else ""
        return f"compadd{suffix} -- {quote(item.value)}"

    return "; ".join(call(item) for item in completions)


class _NoSpaceZshComplete(ZshComplete):
    """ZshComplete that skips the trailing space after a directory candidate.

    Design:
        typer's stock complete() builds one `_arguments '*: :((...))'` list
        for every candidate, which has no per-item nospace hook. Giving each
        candidate its own `compadd` call with the right suffix (see
        _zsh_compadd_script) is the only way to suppress the space for
        directories while keeping it for everything else -- one call per
        item, not one call per type, or grouping by type would silently
        undo the alphabetical order `ls -1p` already gave the candidates.
        This drops the `_describe`-style "value":"help" pairing typer's
        version showed next to each candidate -- an acceptable trade
        against actually completing into a subdirectory.
    """

    def complete(self) -> str:
        args, incomplete = self.get_completion_args()
        completions = self.get_completions(args, incomplete)
        if not completions:
            return "_files"
        return _zsh_compadd_script(completions)


def _prefer_nospace_shell_completers() -> None:
    """Make every future `completion_init()` register the classes above
    instead of typer's stock BashComplete/ZshComplete.

    Design:
        Registering the classes above once, here, at import time is not
        enough: typer's own `completion_init()` re-registers its stock
        classes -- unconditionally overwriting `_available_shells` -- every
        time `app()` runs, which is after this module is imported.
        `completion_init()` calls `add_completion_class` as a free variable,
        resolved from its module's globals at call time rather than at def
        time, so replacing that name on the module survives every future
        call, including ones this process hasn't made yet.
    """

    def _add_completion_class(cls, name):
        if cls is BashComplete:
            cls = _NoSpaceBashComplete
        elif cls is ZshComplete:
            cls = _NoSpaceZshComplete
        return add_completion_class(cls, name)

    _typer_completion_classes.add_completion_class = _add_completion_class  # pyright: ignore


_prefer_nospace_shell_completers()
