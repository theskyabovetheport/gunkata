"""Interactive process selection via fzf, shared by commands that fall back to it."""

import shutil
import subprocess

import typer

from gunkata.ps import ProcessEntry


def fzf_pick_pid(entries: list[ProcessEntry]) -> int | None:
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
    result = subprocess.run(["fzf"], input=listing, stdout=subprocess.PIPE, text=True)
    picked = result.stdout.strip()
    if result.returncode != 0 or not picked:
        return None
    return int(picked.split("\t", 1)[0])
