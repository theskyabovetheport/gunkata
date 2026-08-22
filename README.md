# gunkata

*Designed by a human. Implemented by an LLM.*

Tools to improve security research workflows for Android devices.

## Per-device settings

A device carries its own `GUNKATA_*` defaults, kept under
`$GUNKATA_ROOT/devices/<serial>/settings`:

```bash
gunkata device env --edit    # opens $VISUAL/$EDITOR on export KEY=value lines
gunkata shell id             # uid=0(root) -- the stored setting applies on its own
```

Every command applies the settings of the device it targets. An exported value
outranks a stored one, so `GUNKATA_SHELL_DEFAULT_USER=shell gunkata shell id` runs as
`shell` for that one command without touching the file. `gunkata device env`
(no `--edit`) prints the same settings as `export` lines instead of editing
them -- for handing a device's configuration to something that is not
gunkata.

## Shelling into a device

`gunkata shell [command]` replaces itself with `adb shell` rather than relaying
a command's output: a full-screen program such as `top` draws on the terminal,
`logcat` streams as it goes, keys reach the device, the exit status is the
command's own, and stdout and stderr stay apart. With no command it attaches an
interactive shell instead.

A device pty is asked for only when stdin and stdout are both terminals. A pty
is what tells a full-screen program the size of the window, but it also merges
stderr into stdout and translates newlines -- so `gunkata shell cat <binary>
>file` lands the bytes exactly as the device sent them, terminal or not.

## Mirroring a device with scrcpy

`gunkata scrcpy` mirrors the device inside a nested X server (Xephyr) rather
than running scrcpy's own window directly. That nested server is an ordinary
window as far as any window manager is concerned, so it stays exactly where
it was put -- tiled, floated, or moved -- for as long as the frame itself is
open. scrcpy is only its content: when scrcpy exits, for any reason including
the device rebooting, `gunkata scrcpy` waits for the device to come back and
relaunches scrcpy into that same frame. Nothing about the window's position
is ever read from the window manager or saved to disk -- the frame simply
never closes on its own, which is what makes this work identically under a
tiling or a floating window manager, on X11 or Wayland.

The frame is a normal, resizeable window, so a tiling WM tiles it with no
rule to configure: i3 gives it a tile like anything else, and the nested
screen follows every resize. It opens at this display's own size and there is
no option to change that: Xephyr confines the mouse pointer to the size the
frame opened with, and no later resize widens that box again, so a frame that
opened smaller than the tile it ends up in would have parts you cannot click.
Opening at the full screen size -- the largest tile any window manager can
hand out -- keeps all of it reachable, and shrinking from there is always
safe.

When the frame changes size, scrcpy is relaunched into it rather than left to
re-fit: verified on a real device, a resized scrcpy keeps mapping clicks
against the geometry it started with, so they land progressively too high
towards the bottom of the screen, while a freshly launched one is accurate.
The relaunch is the same one a device reboot triggers, so it costs a second
and the frame never moves.

At startup, `gunkata scrcpy` warns if the host X server is older than X.Org
21.1.22 or the running window manager is i3 older than 4.25.1 -- the only
versions the pointer bound below was measured correct on. The warning says the
combination is untested, not that it is broken: the failure was seen on X.Org
21.1.12 with i3 4.23 and never on 21.1.22 with i3 4.25.1, and since those two
samples differ in both, which component matters is unknown.

After each resize, `gunkata scrcpy` checks that the mouse pointer can still
reach the far corner of the frame, and warns loudly if it cannot. Some X servers
keep bounding the pointer to a rectangle from when the frame was smaller, and
the effect is quiet and confusing: clicks land short of where they were made,
correct near the top-left and worse the further out, as though the device or
scrcpy were at fault. Restarting the session clears it -- the bound belongs to
the frame, so no relaunch of scrcpy helps.

A second small window manager, matchbox-window-manager, runs inside the
nested display alongside scrcpy. Without one there, scrcpy's window has
nothing to size or position it against and opens at its own preferred size
in a corner rather than filling the frame; matchbox keeps it maximized
against the nested screen, whatever size that currently is. The device's own
aspect ratio is preserved inside it, so a frame shaped differently from the
device gets black bars -- pass `--render-fit=stretched` to fill it edge to
edge instead.

While scrcpy is down -- between the device dropping and the relaunch that
follows it -- the frame shows a placeholder naming the device it is waiting
for, rather than the bare black an empty nested screen would otherwise be.
This is cosmetic and optional: `xmessage` draws it, and if it is not on PATH
that is logged and skipped, leaving the gap black.

```bash
gunkata scrcpy                          # mirror the sole attached device
gunkata scrcpy --render-fit=stretched   # unrecognized args pass through to scrcpy
gunkata scrcpy --no-audio               # ... as does anything else scrcpy takes
```

The session ends when the frame window itself is closed, on Ctrl-C, or on a
plain `kill` or a closed terminal -- not when scrcpy's own window closes,
since that is exactly the event this command recovers from. Every ending
tears down Xephyr, matchbox, and scrcpy together; none is ever left
orphaned. The scrcpy binary is fetched from its GitHub releases on first
use into `$GUNKATA_ROOT/dist`, matching how frida-server is provisioned; set
`GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY=1` to allow the fetch, or place a
`scrcpy-linux-x86_64-v<version>.tar.gz` release archive there yourself.
Xephyr and matchbox-window-manager are host packages gunkata does not
install for you: `apt install xserver-xephyr matchbox-window-manager`. The
placeholder's own `xmessage` comes from `x11-utils`, and is the only one
gunkata runs without needing.

## Pulling files, directories, and wildcards

`gunkata pull <dpath> [lpath]` auto-detects what `dpath` names: a plain file
is pulled as itself (atomic, `.gk-part`-then-rename); a wildcard in the final
path component pulls every match, flat, into `lpath`; anything else that is a
directory pulls its whole tree, landing at `lpath/<basename of dpath>` --
`lpath` itself never becomes the tree. `lpath` defaults to the current
directory, and an existing local directory there is always treated as the
destination to land in or under, never renamed onto.

`pull` never creates a local directory to receive a pull: a `lpath` that does
not exist is refused, naming it. A mistyped destination would otherwise report
success and leave the pull somewhere nobody looks. Directories *inside* a
pulled tree are its content, not its destination, and are created as the
archive names them.

A tree pull is not atomic, unlike a single-file pull, and a repeat pull into
the same `lpath` merges: it overwrites the files it re-lands but leaves
whatever else is already there, matching `adb pull`. A wildcard matching
entries under `/proc` lands files that are empty, since a size is read from
each entry's own (zero) reported size rather than its actual content. An
empty directory pulls successfully, landing one empty local directory. A
wildcard matching more entries than the device shell's argument limit allows
surfaces as a loud, ordinary command failure.

## Development

Managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create .venv, install gunkata + deps
uv run gunkata     # run the CLI
uv run gunkata version
```

Tests marked `emulator` need a live adb-attached device. `scripts/run_emulator.sh`
boots one locally (installing the emulator package, a system image, and the AVD
on first run) and leaves it running:

```bash
scripts/run_emulator.sh
uv run pytest -m emulator
```
