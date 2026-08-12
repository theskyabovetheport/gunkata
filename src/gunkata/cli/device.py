"""`gunkata device`: list, pick, name, and tag adb-visible devices."""

import sys

import typer

from gunkata.adb import Adb
from gunkata.cli.app import app
from gunkata.common.paths import Paths
from gunkata.device_config import ListConfig, ListConfigError
from gunkata.device_info import DeviceInfoStore
from gunkata.device_roster import DeviceRoster
from gunkata.localedit import EditorNotFoundError, launch, resolve_editor

device_app = typer.Typer(
    help="List, pick, name, and tag devices adb can currently see.",
    no_args_is_help=True,
)
app.add_typer(device_app, name="device")

tag_app = typer.Typer(help="Add or remove a tag on a device.", no_args_is_help=True)
device_app.add_typer(tag_app, name="tag")


def _roster() -> DeviceRoster:
    """Build the roster from GUNKATA_ROOT's list-config.yaml and info files.

    Raises:
        typer.Exit: list-config.yaml exists but is malformed.
    """
    paths = Paths.from_env()
    try:
        list_config = ListConfig.load(paths.list_config_path)
    except ListConfigError as exc:
        typer.echo(f"{paths.list_config_path}: {exc}", err=True)
        raise typer.Exit(1)
    return DeviceRoster(list_config, DeviceInfoStore(paths))


@device_app.command("list")
def device_list() -> None:
    """Print every adb-visible device as a table: SERIAL, NAME, TAGS, STATE,
    then list-config.yaml's configured columns.
    """
    roster = _roster()
    if not roster.rows():
        typer.echo("no adb devices", err=True)
        return
    typer.echo(roster.render())


@device_app.command("select")
def device_select() -> None:
    """Print the same table, numbered, and prompt for a number.

    The table and prompt go to stderr; only the picked serial goes to
    stdout, so `serial=$(gunkata device select)` captures just the serial.
    Reads the number straight off stdin rather than through typer.prompt --
    click's prompt() writes its final prompt character to real stdout no
    matter what err says (a documented readline workaround), which would
    leak a stray byte ahead of the serial.

    Raises:
        typer.Exit: no devices are visible; stdin didn't hold a number; or
            the entered number is out of range.
    """
    roster = _roster()
    rows = roster.rows()
    if not rows:
        typer.echo("no adb devices", err=True)
        raise typer.Exit(1)
    typer.echo(roster.render(numbered=True), err=True)
    typer.echo("select device number: ", nl=False, err=True)
    raw = sys.stdin.readline().strip()
    try:
        number = int(raw)
    except ValueError:
        typer.echo(f"not a number: {raw!r}", err=True)
        raise typer.Exit(2)
    if not 1 <= number <= len(rows):
        typer.echo(f"no such number: {number}", err=True)
        raise typer.Exit(1)
    typer.echo(rows[number - 1][0])


@device_app.command("name")
def device_name(name: str) -> None:
    """Set the target device's persisted name, replacing whatever was there before.

    The target device resolves the same way every other command's does:
    $ANDROID_SERIAL, else the sole connected device.
    """
    serial = Adb().serial
    DeviceInfoStore(Paths.from_env()).set_name(serial, name)
    typer.echo(f"named {serial} {name!r}")


@tag_app.command("add")
def tag_add(tag: str) -> None:
    """Add tag to the target device's tags. A no-op if it's already present.

    The target device resolves the same way every other command's does:
    $ANDROID_SERIAL, else the sole connected device.
    """
    serial = Adb().serial
    DeviceInfoStore(Paths.from_env()).add_tag(serial, tag)
    typer.echo(f"tagged {serial} {tag!r}")


@tag_app.command("remove")
def tag_remove(tag: str) -> None:
    """Remove tag from the target device's tags. A no-op if it isn't present.

    The target device resolves the same way every other command's does:
    $ANDROID_SERIAL, else the sole connected device.
    """
    serial = Adb().serial
    DeviceInfoStore(Paths.from_env()).remove_tag(serial, tag)
    typer.echo(f"untagged {serial} {tag!r}")


@device_app.command("note")
def device_note(
    message: str = typer.Option(
        None, "-m", help="Note text; omit to compose it in $VISUAL/$EDITOR instead."
    ),
    editor: str = typer.Option(
        None, "--editor", help="Editor to launch when -m is omitted."
    ),
) -> None:
    """Append a timestamped note to the target device's note log.

    The target device resolves the same way every other command's does:
    $ANDROID_SERIAL, else the sole connected device.

    With -m, appends that text directly, git-commit -m style. Without it,
    launches a local editor on an empty buffer, git-commit style; an empty
    or whitespace-only result aborts without appending anything.

    Raises:
        typer.Exit: -m was omitted and no editor is configured; or the
            resulting message is empty.
    """
    serial = Adb().serial
    if message is None:
        try:
            editor_bin = resolve_editor(editor)
        except EditorNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1)
        message = launch(editor_bin, suffix="-gunkata-note.txt").decode()
    if not message.strip():
        typer.echo("empty note, not saved", err=True)
        raise typer.Exit(1)
    DeviceInfoStore(Paths.from_env()).add_note(serial, message)
    typer.echo(f"noted {serial}")
