"""`Device`: bind to and operate one adb-selected device.

`DeviceSettingsStore` lives here too, not in its own module, because
`Device.__init__` is its one library consumer -- per CLAUDE.md's
settings-colocation rule -- and reads it to resolve the persisted `Su`/`Shell`
settings this device's commands should run under. It stores per-serial
GUNKATA_* environment overrides at GUNKATA_ROOT/devices/<serial>/settings, one
`KEY=VALUE` per line -- the same "reads exactly as it looks with cat" shape as
gunkata.inventory.info's name/tags/note files, since this is the fourth file
in that same serial directory. `environment` is the one loader: it drops any
key the process already has in its environment, so a value the caller's shell
fixed is never overridden by a device's own settings. `gunkata device env`
(the CLI's other consumer) goes through the same loader, printing its result
as `export` statements for a shell to eval, so the two can never mean
different things about which value wins.
"""

import os
from enum import Enum

from .adb import Adb
from .common.paths import Paths
from .shell import Shell, ShellSettings
from .su import Su, SuSettings

_COMMENT = "#"


class DeviceState(Enum):
    device = "device"


class DeviceSettingsError(ValueError):
    """Raised when a settings file line isn't a valid KEY=VALUE assignment."""


class DeviceSettingsStore:
    """Reads and writes one device's persisted environment overrides.

    Args:
        paths: Resolves where serial's settings file lives.
    """

    def __init__(self, paths: Paths):
        self._paths = paths

    def load(self, serial: str) -> dict[str, str]:
        """Load serial's persisted KEY=VALUE overrides.

        Returns:
            Every assignment in the file, in file order; {} if serial has no
            settings file yet -- an unset device is a fact, not an error.

        Raises:
            DeviceSettingsError: a non-comment, non-blank line isn't KEY=VALUE.
        """
        path = self._paths.device_settings_path(serial)
        if not path.exists():
            return {}
        settings: dict[str, str] = {}
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(_COMMENT):
                continue
            key, sep, value = stripped.partition("=")
            if not sep or not key.strip():
                raise DeviceSettingsError(f"{path}: not KEY=VALUE: {line!r}")
            settings[key.strip()] = value.strip()
        return settings

    def environment(self, serial: str) -> dict[str, str]:
        """Load serial's overrides, minus whatever the environment already fixes.

        Returns:
            The subset of serial's persisted assignments whose key is absent
            from os.environ, in file order; {} if serial has no settings file.
            A key the caller already exported is dropped rather than returned
            with the persisted value, so the caller's own value always wins.

        Raises:
            DeviceSettingsError: a non-comment, non-blank line isn't KEY=VALUE.

        Design:
            The precedence rule lives here rather than at each consumer: an
            explicit export is a decision the user made for this shell, and a
            device's stored default must not silently overrule it. Two
            consumers implementing that comparison separately is one edit away
            from disagreeing about which wins.
        """
        return {
            key: value
            for key, value in self.load(serial).items()
            if key not in os.environ
        }

    def set(self, serial: str, key: str, value: str) -> None:
        """Set serial's key to value, replacing it if already present."""
        settings = self.load(serial)
        settings[key] = value
        self._write(serial, settings)

    def unset(self, serial: str, key: str) -> None:
        """Remove key from serial's settings. A no-op if it isn't present."""
        settings = self.load(serial)
        settings.pop(key, None)
        self._write(serial, settings)

    def replace(self, serial: str, settings: dict[str, str]) -> None:
        """Replace serial's entire persisted settings with settings.

        Design:
            Unlike set/unset, which mutate one key against whatever was
            already on disk, this takes settings as the complete new state --
            for `device env --edit`'s round trip, which lets a human rewrite
            the whole file freely and must persist exactly what they left,
            including a key they deleted outright.
        """
        self._write(serial, settings)

    def _write(self, serial: str, settings: dict[str, str]) -> None:
        path = self._paths.device_settings_path(serial)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{key}={value}\n" for key, value in settings.items()))


class Device:
    """
    Android device, operated through adb.
    """

    def __init__(self, serial: str | None = None):
        """Bind to serial (or the sole attached device), resolving its persisted settings.

        Args:
            serial: The adb serial to bind to, or None to resolve the same
                way a bare `adb` invocation would -- see Adb.__init__.

        Raises:
            AdbError: serial is None, $ANDROID_SERIAL is unset, and zero or
                more than one device is currently connected.
            DeviceSettingsError: This serial's settings file has a line that
                isn't KEY=VALUE.
            ValidationError: A persisted GUNKATA_* value isn't valid for the
                field it sets.

        Design:
            adb is resolved here rather than taken as a constructor argument:
            Device is the sole owner of "which adb this device's commands
            reach," the same way it is sole owner of "which su" via
            _resolve_su, so a caller is never tempted to hand it an Adb bound
            to a different serial than the one named here. A test that needs
            a fake transport monkeypatches Adb in this module, the same seam
            every CLI command's own Adb reference is patched through.

            The device's stored settings are read here, not in Adb: a caller
            fanning out over every attached serial builds one Adb per device
            (see AdbFactory) and must not pay one settings read per device,
            let alone have one device's stored values reach another's. Device
            is the point where exactly one device becomes the subject.

            persisted is read exactly once and handed to both SuSettings and
            ShellSettings, each of which ignores the other's keys -- reading
            it a second time per settings class would double the file access
            this same invariant (see the persisted-settings entry in
            CLAUDE.md) already forbids.
        """
        self._adb = self._resolve_adb(serial)
        persisted = DeviceSettingsStore(Paths.from_env()).environment(self._adb.serial)
        self._su = self._resolve_su(persisted)
        self._shell_settings = self._resolve_shell_settings(persisted)

    @staticmethod
    def _resolve_adb(serial: str | None) -> Adb:
        return Adb(serial)

    @staticmethod
    def _resolve_su(persisted: dict[str, str]) -> Su:
        """Build this device's Su from its persisted+exported settings.

        Design:
            persisted is passed as constructor arguments, which outrank a
            BaseSettings field's default but was already filtered against
            os.environ by DeviceSettingsStore.environment -- so the
            resulting precedence is environment, then persisted, then
            default, matching what `device env` produces when eval'd into a
            shell. SuSettings ignores extra keys, so this device's unrelated
            GUNKATA_* settings pass through untouched.
        """
        return Su(SuSettings(**persisted))

    @staticmethod
    def _resolve_shell_settings(persisted: dict[str, str]) -> ShellSettings:
        """Build this device's ShellSettings from its persisted+exported settings.

        Design:
            Same precedence and same extra-key tolerance as _resolve_su, for
            the same reason: ShellSettings ignores this device's unrelated
            GUNKATA_* settings, so persisted is shared between both resolvers
            without either caring about the other's fields.
        """
        return ShellSettings(**persisted)

    @property
    def serial(self) -> str:
        return self._adb.serial

    def get_state(self) -> str:
        return self._adb(["get-state"], capture_output=True, text=True).stdout.strip()

    def wait_for_state(self, state: DeviceState | str):
        self._adb([f"wait-for-{DeviceState(state).value}"])

    def shell(self, user: str | None = None) -> Shell:
        """Bind a Shell to user, or to this device's default_user when user is None.

        Args:
            user: The user to run commands as, or None for the unqualified
                default every bare `shell()` call, and every CLI command,
                resolves to: this device's configured default_user. `gunkata`
                itself carries the CLI's one -U/--user option, at the root
                -- see `cli/app.py` -- rather than any individual command.

        Returns:
            A Shell bound to user (or default_user). "shell" is never wrapped
            through su, reached via default_user or named explicitly; every
            other user always is -- see Su.wrap.

        Raises:
            ValueError: the resolved user is neither "shell" nor "root" and
                this device's su command template has no {user} placeholder
                to carry it -- see Su.wrap.

        Design:
            The None check lives in Shell.__init__, not here: Device passes
            user through unresolved, along with this device's ShellSettings,
            and Shell resolves its own default the same way it resolves its
            own su-wrapping through Su -- Device wires collaborators
            together without reaching into either one's settings. has_root
            calls the bare form rather than shell(user="root") for a related
            reason: it measures what default_user actually grants, not what
            an explicit override could force.
        """
        return Shell(self._adb, user=user, su=self._su, settings=self._shell_settings)

    def has_root(self) -> bool:
        """Whether this device's su configuration actually lands a command at root.

        Returns:
            True when a command wrapped as root reports uid 0. False when it
            reports any other uid, and when su is missing, denied, or disabled
            for this device -- each of those leaves the caller without root,
            which is the only distinction this answers.

        Design:
            Asks the device rather than reading GUNKATA_SHELL_DEFAULT_USER,
            which records what was configured, not what the device grants:
            su can be absent from the image, or a manager app can deny the
            request, with the setting still naming root. A caller about to
            attempt a root-only read needs what is true on the device.

            `id -u` rather than `id`: one token to compare, with no locale- or
            build-dependent wording to parse. A non-zero exit is reported as
            False rather than raised, because "su refused" is the answer this
            was asked for, not a failure to produce one.
        """
        result = self.shell().sh("id -u")
        return result.ok and result.stdout.strip() == "0"
