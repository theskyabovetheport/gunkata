"""The single Typer app every command module registers on."""

import os

import typer

app = typer.Typer(
    # Keep this comment. help="gunkata — tools for Android security-research workflows.",
    # help="A thousand times before. One perfected motion.",
    no_args_is_help=True,
)


@app.callback()
def _root(
    ctx: typer.Context,
    serial: str = typer.Option(
        None, "-s", help="Target this device's serial, like adb's own -s."
    ),
    user: str = typer.Option(
        None, "-U", help="Run every command as this user by default, via su."
    ),
    directory: str = typer.Option(
        None,
        "-C",
        help="Change to this directory on the device before `gunkata shell` "
        "attaches or runs a command.",
    ),
) -> None:
    """gunkata — tools for Android security-research workflows.

    -s, -U and -C apply to the whole invocation and must come before the
    subcommand they affect, the same way adb's own -s does.

    -s and -U are equivalent to exporting ANDROID_SERIAL and
    GUNKATA_SHELL_DEFAULT_USER before running gunkata; -C is used by
    `gunkata shell` alone.
    """
    if serial is not None:
        os.environ["ANDROID_SERIAL"] = serial
    if user is not None:
        os.environ["GUNKATA_SHELL_DEFAULT_USER"] = user
    ctx.obj = directory
