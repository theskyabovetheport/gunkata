# gunkata

*Designed by a human. Implemented by an LLM.*

Tools to improve security research workflows for Android devices.

> Through analysis of thousands of recorded interactions with Android
> devices, the Hacker has determined that the sequence of commands, actions,
> and system states in any device interaction is a statistically predictable
> element.

## What it is

gunkata is a command line and a Python library built directly on the `adb`
binary: no daemon, no protocol of its own, no agent of its own on the device
-- what it does push there, frida-server and scrcpy's server, is upstream's
own, provisioned on demand.

One idea carries every command: a command reaches the device through `su`,
as a user chosen once per device. Configure a device for root and everything
runs as root -- `pull`, `push`, `edit`, `ps`, `procmaps`, `mem`, even tab
completion of a remote path -- with no `su -c` typed in front of it and no
command quoted to survive two shells. `adb` hands you the `shell` user and
leaves the rest to you; gunkata makes the user a property of the device.

Around that:

- device selection exactly as `adb` does it, plus a table, a picker, and a
  name, tags and notes per device that survive reconnects;
- process introspection from the host: `ps`, `pidof`, `/proc/<pid>/maps`, an
  address locator, and raw reads and writes through `/proc/<pid>/mem`;
- frida-server provisioned and supervised on the device;
- scrcpy inside a frame that outlives the device's reboots.

The library exposes the objects the commands are built from -- `Device`,
`Shell`, `Logcat`, `ProcMaps`, `Memory`, `FridaServer`, `ScrcpySession` --
with the same semantics.

## Requirements

- `adb` on PATH, and a device it can see.
- Root on the device, for anything that needs it: an `su` the `shell` user
  may call (Magisk, or any su whose command line `GUNKATA_SU_COMMAND` can
  spell), or an emulator image where `adb root` works -- there `adb shell`
  is root already and su is not involved.
- Python 3.12 or later.
- Optional, each needed only by the command that uses it: `fzf`, for
  `pidof`/`procmaps` with no target; the `frida` package (`gunkata[frida]`),
  for connecting a client -- provisioning the server needs no frida, given a
  version; `Xephyr`, `matchbox-window-manager` and `xmessage`, for
  `gunkata scrcpy`.

## Install

From a checkout:

```bash
uv tool install .                 # the gunkata command, on PATH
uv tool install . --with frida    # with the frida client
gunkata --install-completion      # remote paths and process names, see below
```

Before anything else, in the shell's rc file:

```bash
alias gk=gunkata
```

zsh completes `gk` exactly as it completes `gunkata`. bash does not see
through an alias -- its completion function runs the word as typed -- so
there `gk` is a symlink to the `gunkata` script instead, registered with
`gk --install-completion`.

## Choosing the device

Every command targets one device, resolved the way `adb` itself does: the
serial given with `gunkata -s`, else `$ANDROID_SERIAL`, else the sole
connected device -- zero or several is a refusal. `-s` is a global option
that precedes the subcommand, like `adb -s`.

```bash
gunkata devices                                  # SERIAL NAME TAGS STATE + configured columns
gunkata devices --select                         # the same table numbered, a prompt, and the picked serial alone on stdout
gunkata device name pixel-lab                    # persisted across reconnects, shown in the table
gunkata device tag add rooted
gunkata device note -m "bootloader unlocked"     # appended to a timestamped log; -m omitted opens $EDITOR
```

`--select` keeps its table and prompt on stderr, so its stdout drops
straight into an `export`. Recommended, in the shell's rc file:

```bash
alias s='export ANDROID_SERIAL=$(gunkata devices --select)'    # pick this shell's device
alias serial='gunkata devices --select >~/.serial && export ANDROID_SERIAL=$(cat ~/.serial)'   # pick every shell's
export ANDROID_SERIAL=$(cat ~/.serial 2>/dev/null)             # a new shell starts on the device `serial` picked
```

A cancelled pick leaves the variable empty, which `adb` and gunkata both
read as unset.

Columns beyond the fixed four come from `list-config.yaml` (`gunkata devices
--edit`): each is a `getprop` key or a `shell` command, and the built-in
default shows the model. A device adb lists but cannot reach shows `-` in
its cells rather than failing the table.

## Running as root

A device's default user is `GUNKATA_SHELL_DEFAULT_USER`. `shell`, the
built-in default, sends commands as adb's own user; any other value wraps
every command through su as that user -- `su root sh -c '<command>'`, quoted
for you. Set it once per device and every command picks it up:

```bash
gunkata device env --edit     # opens an editor on: export GUNKATA_SHELL_DEFAULT_USER=root
gunkata shell id              # uid=0(root)
gunkata pull /data/data/com.example.app/databases/app.db
```

Stored settings live beside the device's name and tags, one `KEY=VALUE` per
line, and an exported value outranks a stored one: `gunkata -U shell shell
id`, or `GUNKATA_SHELL_DEFAULT_USER=shell gunkata shell id`, runs that one
command unwrapped without touching the file. `gunkata device env` prints
what is stored -- minus whatever the shell already exports -- as `export`
lines, for `eval` into a shell driving a bare `adb` or a debugger with the
same settings.

A device whose su takes a different command line sets `GUNKATA_SU_COMMAND`,
a template with `{user}` and `{command}` placeholders written bare; gunkata
quotes `{command}` itself, and a template carrying its own quotes is
refused. These two are the settings a command reads from the device's file
on its own. Every other `GUNKATA_*` variable -- frida, scrcpy, logging --
comes from the environment, so one stored per device reaches a command
through `eval "$(gunkata device env)"`.

Tab completion runs as the same user the completed command will, so a
root-only directory completes on a device configured for root. A directory
completes without a trailing space, so a second Tab continues into it.

## Shell

`gunkata shell [command...]` replaces itself with `adb shell` rather than
relaying output: `top` draws, `logcat` streams, keys reach the device, the
exit status is the command's own, and stdout and stderr stay apart. A device
pty is asked for only when stdin and stdout are both terminals -- a pty is
what tells a full-screen program its window size, but it also merges stderr
into stdout and translates newlines -- so `gunkata shell cat <binary> >file`
lands the bytes exactly as the device sent them. `-C` changes directory
first.

```bash
gunkata shell                                        # interactive, as the default user
gunkata shell top                                    # full-screen at the window's size, following a resize; the terminal is left as it was on exit
gunkata -U root -C /data/data/com.example.app shell  # a root shell, already in the app's directory
gunkata shell ls -ld '/data/app/*'                   # a quoted glob survives to the device's shell
```

## Files

`gunkata pull <dpath> [lpath]` pulls whatever `dpath` names:

```bash
gunkata pull /data/data/com.example.app/shared_prefs/prefs.xml    # one file, into the current directory
gunkata pull /data/data/com.example.app dumps                      # the whole tree, at dumps/com.example.app/
gunkata pull '/data/data/com.example.app/databases/*.db' dumps     # every match, flat, into dumps/
```

A single file lands atomically (a `.gk-part` sibling, renamed into place).
`lpath` must already exist -- a destination that does not is refused,
naming it, so a typo cannot report success and land the pull where nobody
looks. A tree pull merges into what is already there, overwriting what it
re-lands and leaving the rest; an archive member that would land outside
the destination (an absolute symlink, a `..` component) is skipped and
named. A wildcard is accepted in the last path component only, and a device
path holding shell metacharacters -- a space included -- is refused rather
than quoted.

`gunkata push <lpath> <dpath>` takes adb's own argument order; a directory
at `dpath` receives the file under its local basename. The written file is
chowned to its parent directory's owner (`--no-inherit-owner` leaves it to
the pushing user), so a file pushed as root into an app's data directory
belongs to the app.

`gunkata edit <dpath>` is sudoedit for a device file: pulled to a temp file,
opened in `--editor`, `$VISUAL` or `$EDITOR`, and pushed back only if its
bytes changed. A missing file starts as an empty buffer and is created on
save, provided its parent directory exists; only a file created this way is
chowned to its directory's owner, an existing file keeps its own.

## Processes and memory

```bash
gunkata ps                                   # PID NAME table; plain "pid name" lines when piped
gunkata pidof com.example.app                # one pid per line; no argument picks one with fzf
gunkata procmaps -P com.example.app          # /proc/<pid>/maps, byte for byte; -p <pid>; neither picks with fzf
gunkata addr 7fffc274f000+0x1000 -P com.example.app -B 2 -A 2
gunkata addr 7fffc274f000+0x1000 < saved.maps   # a listing on stdin, when neither -p nor -P is given
gunkata mem read -P com.example.app -s 0x7fffc274f000 -e 0x7fffc274f000+0x40
gunkata mem write -p $(gunkata pidof com.example.app) -s 0x7fffc274f000 -e 0x7fffc274f040 < patch.bin
```

`addr` takes the listing from the process `-p` or `-P` names, or from
stdin when neither is given, and prints the mapping the address falls in
with grep-style `-A`/`-B` context, the matched line annotated
`// contained +<offset from its start> -<distance to its end>`; an address
in a gap annotates the mappings on either side of it instead (`below`,
`above`). An address is hex with `0x` optional, so one copied straight from
a maps line needs no editing, and `+`/`-` offsets chain onto it.

`mem read` prints a hex dump on a terminal and raw bytes when piped; `mem
write` writes stdin's bytes at `-s`, and refuses rather than truncates when
`-e` would be crossed. Both target a process by exactly one of `-p` and
`-P`, and both check the whole range against a freshly read
`/proc/<pid>/maps` before touching
`/proc/<pid>/mem` -- a range not fully mapped is a refusal. The bytes move
through `dd bs=1`, one syscall per byte, so a range is sized to what is
needed.

## frida

```bash
gunkata frida start        # provisions frida-server if the device lacks it, then starts it detached
gunkata frida status       # exit status says whether it runs, for a script to gate on
gunkata frida stop
```

Provisioning reads the device's ABI and takes
`frida-server-<version>-android-<arch>.xz` from `$GUNKATA_ROOT/dist`, the
version defaulting to the installed `frida` package's (client and server
must match) or given with `--version`. A missing archive is refused unless
`GUNKATA_FRIDA_AUTODOWNLOAD_SERVER_BINARY=1` lets it be fetched from frida's
GitHub releases. The server binds loopback on `GUNKATA_FRIDA_PORT` (`-p`),
runs as the device's default user -- root, for ptrace -- and stays up until
`stop`. A server something else manages is declared with
`GUNKATA_FRIDA_ASSUME_RUNNING=1`: `start` then touches nothing and `stop`
refuses.

From Python, `FridaServer.running()` scopes a server to a `with` block and
reaps it after, and `get_device()` returns the `frida` device for this
serial once its server answers.

## scrcpy

`gunkata scrcpy` mirrors the device in a window that outlives it: across a
reboot or a dropped connection the window shows a placeholder naming the
device, then picks the mirror up again in place, wherever a tiling or a
floating window manager put it. The window is titled `gunkata:<serial>`,
opens at the host screen's size, and has no size option -- resize it with
the window manager.

```bash
gunkata scrcpy                          # mirror the device
gunkata scrcpy --render-fit=stretched   # unrecognized arguments pass through to scrcpy
gunkata scrcpy --no-audio
```

The session ends when the window is closed, on Ctrl-C, or on a plain `kill`
or a closed terminal -- never when scrcpy's own content exits, which is the
event it recovers from. Two warnings can appear: at startup, a host X server
or i3 older than the versions this was measured on is reported as untested;
after a resize, a pointer that cannot reach the window's far corner is
reported with its bound -- clicks then land short of where they were made,
and restarting the session clears it.

Linux x86_64 only. Xephyr and matchbox-window-manager are host packages
(`apt install xserver-xephyr matchbox-window-manager`); `xmessage`
(`x11-utils`) paints the placeholder and is skipped, with a log line, when
absent. The scrcpy release is taken from `$GUNKATA_ROOT/dist` as
`scrcpy-linux-x86_64-v<version>.tar.gz`, or fetched from its GitHub
releases with `GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY=1` and checked against the
release's published checksum first.

## Python

```python
from gunkata import Device, Level, Logcat, Memory, ProcMaps

device = Device()                        # -s / $ANDROID_SERIAL / sole device, its settings applied
shell = device.shell()                   # as the device's default user; shell(user="root") forces one
print(shell.sh("id -u").stdout)          # ShellResult: stdout, stderr, rc, ok
shell.pull("/data/data/com.example.app", "dumps")

maps = ProcMaps.by_name(shell, "com.example.app")
mapping = maps.find(0x7FFFC274F000)      # the MemoryMapping containing the address, or None
pid = shell.pidof("com.example.app")[0]
data = Memory(shell, pid).read(mapping.start, mapping.start + 0x40)

with Logcat(shell, tags={"ActivityManager": Level.W}).follow_for(30) as entries:
    for entry in entries:                # LogcatEntry: time, pid, tid, level, tag, message, raw
        ...
```

`Shell.stream(command)` follows any long-running device command line by
line and ends it when its reader stops, whether by `break`, an exception or
a timer; `Logcat` is built on it, and by default starts at the live tail
rather than replaying the ring buffer. `Shell.pull`, `push_file`,
`read_file`, `write_file` and `execvp_sh` are what the commands above call.
As a library gunkata configures no logging; the `gunkata` command sets the
root logger's level from `GUNKATA_LOG_LEVEL`.

## State on disk

Everything gunkata persists lives under `$GUNKATA_ROOT`, `~/.gunkata` by
default, resolved by `Paths`. `devices/<serial>/` holds one plain-text file
per kind of per-device state -- the name, the tags, the note log, the
settings -- each reading with `cat` exactly as it looks; `devices/` also
holds `list-config.yaml`, and `dist/` caches every downloaded release
archive. On the device, the one thing that persists is the frida-server
binary `frida start` pushes, at `GUNKATA_FRIDA_DEVICE_PATH`.

## Development

Managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync            # create .venv, install gunkata + deps + dev tools
uv run gunkata     # run the CLI
uv run gunkata version
```

`scripts/check.sh` runs every gate this repo has -- lint (`ruff`), a docs
build (`mkdocs build --strict`, serving `README.md` itself as `docs/index.md`,
a symlink), then the test suite:

```bash
scripts/check.sh
```

Tests marked `emulator` need a live adb-attached device. `scripts/run_emulator.sh`
boots one locally (installing the emulator package, a system image, and the AVD
on first run) and leaves it running:

```bash
scripts/run_emulator.sh
uv run pytest -m emulator
```
