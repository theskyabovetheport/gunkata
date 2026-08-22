"""`gunkata device`: name, tag, and configure the target device.

Listing and picking *across* every adb-visible device live at the top level
instead, `gunkata devices`/`gunkata devices --select`, not under this group
-- see this module's `devices`.
"""

import shlex
import sys

import typer

from gunkata.adb import Adb, AdbFactory
from gunkata.cli.app import app
from gunkata.common.paths import Paths
from gunkata.device import DeviceSettingsError, DeviceSettingsStore
from gunkata.inventory.info import DeviceInfoStore
from gunkata.inventory.list_config import ListConfig, ListConfigError
from gunkata.inventory.roster import DeviceRoster
from gunkata.localedit import EditorNotFoundError, launch, resolve_editor

device_app = typer.Typer(
    help="Name, tag, and configure the target device.",
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
    return DeviceRoster(list_config, DeviceInfoStore(paths), AdbFactory())


# One function under two names, so `gunkata devices` and `gunkata device list`
# can never drift apart.
@app.command("devices")
def devices(
    edit: bool = typer.Option(
        False,
        "-e",
        "--edit",
        help="Edit list-config.yaml in $VISUAL/$EDITOR instead of listing.",
    ),
    select: bool = typer.Option(
        False,
        "--select",
        help="Print the table numbered, prompt for a number, and print only "
        "the picked serial to stdout.",
    ),
) -> None:
    """List every device adb can see, one per row.

    Columns are SERIAL, NAME, TAGS and STATE, followed by whatever extra
    columns list-config.yaml configures.

    With --edit, opens list-config.yaml in $VISUAL/$EDITOR instead --
    starting from the built-in default when there is no file yet. Saving
    replaces the file with whatever is left; an edit that would leave it
    unreadable is refused rather than written.

    With --select, prints the same table numbered and prompts for a number.
    Table and prompt go to stderr and only the picked serial goes to stdout,
    so `serial=$(gunkata devices --select)` captures just the serial.

    Pass at most one of --edit/--select.
    """
    if edit and select:
        typer.echo("pass at most one of --edit/--select", err=True)
        raise typer.Exit(2)
    if edit:
        _edit_list_config()
        return
    if select:
        _select_device()
        return
    roster = _roster()
    if not roster.rows():
        typer.echo("no adb devices", err=True)
        return
    typer.echo(roster.render())


def _edit_list_config() -> None:
    paths = Paths.from_env()
    try:
        editor_bin = resolve_editor()
    except EditorNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    current = ListConfig.read_body(paths.list_config_path)
    edited = launch(
        editor_bin, initial=current.encode(), suffix="-gunkata-list-config.yaml"
    )
    try:
        ListConfig.parse(edited.decode())
    except ListConfigError as exc:
        typer.echo(f"not saved: {exc}", err=True)
        raise typer.Exit(1)
    paths.list_config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.list_config_path.write_bytes(edited)
    typer.echo(f"saved {paths.list_config_path}")


def _select_device() -> None:
    """Print the roster numbered, prompt for a number, and print only the
    picked serial to stdout -- `devices`'s own `--select` behavior.

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
    # Read the number off stdin directly rather than via typer.prompt: click's
    # prompt() writes its final prompt character to real stdout regardless of
    # err (a documented readline workaround), leaking a byte ahead of the
    # serial this command's stdout is reserved for.
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
    """Name the target device, replacing any name it already had.

    Targets the device named by -s or $ANDROID_SERIAL, else the sole
    connected device.
    """
    serial = Adb().serial
    DeviceInfoStore(Paths.from_env()).set_name(serial, name)
    typer.echo(f"named {serial} {name!r}")


@tag_app.command("add")
def tag_add(tag: str) -> None:
    """Tag the target device. A no-op if the tag is already there.

    Targets the device named by -s or $ANDROID_SERIAL, else the sole
    connected device.
    """
    serial = Adb().serial
    DeviceInfoStore(Paths.from_env()).add_tag(serial, tag)
    typer.echo(f"tagged {serial} {tag!r}")


@tag_app.command("remove")
def tag_remove(tag: str) -> None:
    """Remove a tag from the target device. A no-op if it isn't there.

    Targets the device named by -s or $ANDROID_SERIAL, else the sole
    connected device.
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

    With -m, appends that text directly, git-commit -m style. Without it,
    opens an empty buffer in $VISUAL/$EDITOR; an empty or whitespace-only
    note is discarded rather than appended.

    Targets the device named by -s or $ANDROID_SERIAL, else the sole
    connected device.
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


@device_app.command("env")
def device_env(
    edit: bool = typer.Option(
        False,
        "-e",
        "--edit",
        help="Edit the exports in $VISUAL/$EDITOR instead of printing them.",
    ),
) -> None:
    """Print the target device's stored settings as `export KEY=value` lines.

    Every gunkata command already applies these settings itself, so this is
    for handing them to something else -- a bare `adb`, a debugger, or any
    script that reads GUNKATA_* directly:

      eval "$(gunkata device env)"

    A key already exported in the current shell is left out, so an explicit
    export always wins over the device's stored value.

    With --edit, opens the same export lines in $VISUAL/$EDITOR, including
    any key the current shell shadows. Saving replaces the device's stored
    settings with whatever lines are left: delete a line to unset a key,
    change a value to re-set it, add a line to set a new one.

    Targets the device named by -s or $ANDROID_SERIAL, else the sole
    connected device.
    """
    serial = Adb().serial
    store = DeviceSettingsStore(Paths.from_env())
    if edit:
        _edit_env(store, serial)
        return
    try:
        settings = store.environment(serial)
    except DeviceSettingsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    for key, value in settings.items():
        typer.echo(f"export {key}={shlex.quote(value)}")


def _edit_env(store: DeviceSettingsStore, serial: str) -> None:
    try:
        current = store.load(serial)
    except DeviceSettingsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    try:
        editor_bin = resolve_editor()
    except EditorNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)
    edited = launch(
        editor_bin, initial=_format_exports(current).encode(), suffix="-gunkata-env.sh"
    )
    try:
        settings = _parse_exports(edited.decode())
    except DeviceSettingsError as exc:
        typer.echo(f"not saved: {exc}", err=True)
        raise typer.Exit(1)
    store.replace(serial, settings)
    typer.echo(f"saved {serial}'s settings")


def _format_exports(settings: dict[str, str]) -> str:
    return "".join(
        f"export {key}={shlex.quote(value)}\n" for key, value in settings.items()
    )


def _parse_exports(text: str) -> dict[str, str]:
    """Parse `export KEY=value` lines back into a settings dict.

    Raises:
        DeviceSettingsError: a non-comment, non-blank line isn't a single
            `export KEY=value` assignment.
    """
    settings: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = shlex.split(stripped)
        except ValueError as exc:
            raise DeviceSettingsError(f"not export KEY=value: {line!r}: {exc}") from exc
        if len(tokens) != 2 or tokens[0] != "export" or "=" not in tokens[1]:
            raise DeviceSettingsError(f"not export KEY=value: {line!r}")
        key, _, value = tokens[1].partition("=")
        if not key:
            raise DeviceSettingsError(f"not export KEY=value: {line!r}")
        settings[key] = value
    return settings
