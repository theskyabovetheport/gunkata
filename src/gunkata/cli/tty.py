"""Terminal-detection seams shared by commands that behave differently on a tty.

Design:
    Each is a one-line wrapper a test can monkeypatch. Typer's CliRunner
    replaces ``sys.stdin``/``sys.stdout`` for the duration of an invocation,
    so a test can't patch the real stream beforehand and have it take effect
    -- it patches the importing command module's reference to these functions
    instead.
"""

import sys


def stdin_is_tty() -> bool:
    """Whether stdin is a terminal."""
    return sys.stdin.isatty()


def stdout_is_tty() -> bool:
    """Whether stdout is a terminal."""
    return sys.stdout.isatty()
