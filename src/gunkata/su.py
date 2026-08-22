"""Environment-resolved settings, kept apart from the schemas in types.py
because these read the environment on construction rather than being handed
their values by whatever builds them."""

import shlex

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SuSettings(BaseSettings):
    """Environment-resolved fields describing how to invoke su.

    Attributes:
        command: The command line to build, as a template with ``{user}``
            and ``{command}`` placeholders, spaced as any other word --
            ``{user}`` substitutes to the empty string when the resolved
            user is empty, and Su.wrap collapses the resulting run of
            whitespace. ``{command}`` is always substituted via
            ``shlex.quote``, so a template must write it bare: Su.wrap
            already supplies exactly the quoting the assembled command
            needs. A template containing a single quote anywhere -- around
            ``{command}`` or elsewhere -- is rejected at construction; see
            Su.__init__.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    command: str = Field(
        "su {user} sh -c {command}", validation_alias="GUNKATA_SU_COMMAND"
    )


class Su:
    """Whether and how to invoke su before running a device command."""

    def __init__(self, settings: SuSettings | None = None, **overrides):
        """Build from settings, or resolve fresh ones from the environment.

        Args:
            overrides: Take each field over its environment-resolved default
                -- an explicit constructor argument a caller already had.
                None skips the field rather than reaching SuSettings, whose
                fields are typed non-optional.

        Raises:
            ValueError: settings.command contains a single quote. Su.wrap
                always supplies {command}'s quoting itself, so a template
                that adds its own would double-quote it the moment a command
                needed escaping. Raised here, at construction, so a
                misconfigured template fails immediately rather than
                corrupting some later command silently.
        """
        if settings is not None:
            self.settings = settings
        else:
            given = {
                key: value for key, value in overrides.items() if value is not None
            }
            self.settings = SuSettings(**given)
        if "'" in self.settings.command:
            raise ValueError(
                f"su command {self.settings.command!r} must not contain a "
                "single quote: Su.wrap already quotes {command} for you, so "
                "the template must write the placeholder bare"
            )

    def wrap(self, command: str, user: str) -> str:
        """Build this device's command line to run command as user.

        Returns:
            command unchanged if user is "shell"; otherwise command built
            per settings.command, e.g. ``su root sh -c id``. Whatever the
            caller sends as command runs exactly as given -- su-invocation
            quoting is this method's own concern, invisible to the caller.

        Raises:
            ValueError: user is neither "shell" nor "root" and this Su's
                command template has no {user} placeholder to carry it.

        Design:
            "shell" is the sole branch point: it names adb's own already-
            unprivileged user, not an su target, so wrapping it would ask su
            for a no-op at best and a rejected request at worst -- every
            other user always wraps, with no separate enabled/disabled
            state to override. "root" is exempt from the placeholder check:
            it is su's own no-argument default, and some su binaries reject
            an explicit user entirely, so dropping the placeholder for it is
            the correct wrap, not a lossy one. command is substituted last,
            after collapsing the whitespace an empty {user} leaves behind,
            so a run of spaces inside command itself is never touched by
            that collapse.

            command is always substituted via shlex.quote -- every command is
            escaped, whether or not it happens to need it. Whatever sits after
            {command} in the template (an inner shell's ``-c``, a wrapper
            script's own argv) receives command as one shell word,
            reconstructable byte-for-byte, whatever it contains; a command
            that already quotes something (``find ... -name '*'``) would
            otherwise close the template's own quoting early and leak a bare
            glob to whatever runs it. A safe command with nothing to escape
            comes back unquoted, exactly the bytes it was.
        """
        if user == "shell":
            return command
        if user != "root" and "{user}" not in self.settings.command:
            raise ValueError(
                f"cannot run as {user!r}: su command {self.settings.command!r} "
                "has no {user} placeholder"
            )
        preamble = self.settings.command.format(user=user, command="{command}")
        preamble = " ".join(preamble.split())
        return preamble.format(command=shlex.quote(command))
