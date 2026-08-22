"""`gunkata shell`: run a one-shot command via su, or attach interactively."""

import shlex

import typer

from gunkata.cli.app import app
from gunkata.cli.completion import complete_remote_path
from gunkata.cli.passthrough import PASSTHROUGH
from gunkata.cli.tty import stdin_is_tty, stdout_is_tty
from gunkata.device import Device


@app.command(context_settings=PASSTHROUGH)
def shell(
    ctx: typer.Context,
    command: list[str] = typer.Argument(None, autocompletion=complete_remote_path),
) -> None:
    """Open a shell on the device, or run one command on it and exit.

    Runs as the default user, via su unless that user is `shell`; pass
    `gunkata -U <user>` to pick another. With no command, attaches
    interactively.
    """
    # command already arrived as argv tokens -- the invoking shell resolved
    # any quoting of its own before this process ever saw it. shlex.join
    # re-quotes each token so a token like a guarded glob survives as the
    # same literal value once the device's shell parses this string again.
    Device().shell().execvp_sh(
        command=shlex.join(command) if command else None,
        # Set by `gunkata`'s own -C, which must precede this command the way
        # adb's own -s precedes its subcommand -- see app.py's root callback.
        directory=ctx.obj,
        # Both ends, not just stdin as adb's own -t tests: a pty would put a
        # terminal's line discipline between the device and a redirected
        # stdout, corrupting `gunkata shell cat <binary> >file`.
        pty=stdin_is_tty() and stdout_is_tty(),
    )
