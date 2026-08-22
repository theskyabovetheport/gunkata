"""Entry point for the ``gunkata`` console script.

Imports every command module so each one's ``@app.command()``/``@mem_app.command()``
registration runs, then hands off to the shared Typer app.
"""

from gunkata.cli import (  # noqa: F401 -- imported for their command-registration side effect
    addr,
    device,
    edit,
    frida,
    mem,
    pidof,
    procmaps,
    ps,
    pull,
    push,
    scrcpy,
    shell,
    version,
)
from gunkata.cli.app import app
from gunkata.cli.logging_config import configure_logging


def main() -> None:
    """Entry point for the ``gunkata`` console script."""
    configure_logging()
    app()
