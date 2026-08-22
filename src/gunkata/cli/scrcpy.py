"""`gunkata scrcpy`: mirror a device inside a frame that outlives its reboots."""

import signal

import typer

from gunkata.cli.app import app
from gunkata.cli.passthrough import PASSTHROUGH
from gunkata.common.download import BinaryDownloadError
from gunkata.device import Device
from gunkata.scrcpy.repo import (
    ScrcpyAssetError,
    ScrcpyChecksumError,
    UnsupportedHostError,
)
from gunkata.scrcpy.session import ScrcpyBootTimeoutError, ScrcpyLaunchError, ScrcpySession
from gunkata.scrcpy.settings import ScrcpySettings
from gunkata.scrcpy.xephyr import (
    FrameDisplayError,
    MatchboxUnavailableError,
    NoDisplayError,
    XephyrUnavailableError,
)

# Every way a session can fail with a message the user can act on: no scrcpy
# build for this host, no archive to provision it from, a corrupt download, no
# X server to frame it in, no Xephyr or matchbox-window-manager installed, the
# frame's own display refusing to answer, the device never coming back from a
# reboot, or scrcpy itself stuck in a launch loop. Each names its own fix, so
# the message is the whole of what a traceback would bury.
_SESSION_FAILURES = (
    UnsupportedHostError,
    ScrcpyAssetError,
    BinaryDownloadError,
    ScrcpyChecksumError,
    NoDisplayError,
    XephyrUnavailableError,
    MatchboxUnavailableError,
    FrameDisplayError,
    ScrcpyBootTimeoutError,
    ScrcpyLaunchError,
)


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


@app.command(context_settings=PASSTHROUGH)
def scrcpy(ctx: typer.Context) -> None:
    """Mirror the device inside a nested X frame that outlives device reboots.

    Extra arguments are passed through to scrcpy verbatim.

    The frame opens at this display's own size and is resized by whatever
    manages it, so there is no size to pass here.
    """
    session = ScrcpySession(
        Device(), settings=ScrcpySettings(), extra_args=list(ctx.args)
    )
    # SIGTERM (a plain `kill`) and SIGHUP (a closed terminal) have no default
    # translation into a Python exception the way SIGINT's default handler
    # does -- their default action ends this process immediately, skipping
    # every `finally` session.run() unwinds through and orphaning Xephyr,
    # matchbox, and scrcpy. Raising KeyboardInterrupt from them instead
    # routes both through the same teardown Ctrl-C already triggers.
    previous_term = signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    previous_hup = signal.signal(signal.SIGHUP, _raise_keyboard_interrupt)
    try:
        session.run()
    except _SESSION_FAILURES as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except KeyboardInterrupt:
        raise typer.Exit(130) from None
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGHUP, previous_hup)
