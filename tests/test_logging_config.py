"""Guard for gunkata's own logging discipline: every module logs via `__name__`."""

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _getlogger_call_args(source: str) -> list[ast.expr | None]:
    """Every argument expression passed to a `logging.getLogger(...)` call in `source`."""
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getLogger"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logging"
        ):
            calls.append(node.args[0] if node.args else None)
    return calls


def test_every_logger_descends_from_package_root():
    """Every `logging.getLogger(...)` call under `src/gunkata` must pass `__name__`.

    A module's logger name must equal its own dotted module path. Every module
    lives under the `gunkata` package, so that path already makes it a
    descendant of `"gunkata"` -- no separate root-name constant is needed to
    state that. A string literal or the bare root logger would silently opt
    that module out of the hierarchy the package promises.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "src/gunkata"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.splitlines()
    offenders = []
    for rel_path in tracked:
        if not rel_path.endswith(".py"):
            continue
        path = REPO_ROOT / rel_path
        for call_arg in _getlogger_call_args(path.read_text()):
            if not (isinstance(call_arg, ast.Name) and call_arg.id == "__name__"):
                offenders.append(rel_path)
    assert not offenders, (
        f"logging.getLogger(...) must be called with __name__, not a literal "
        f"or the bare root logger: {offenders}"
    )
