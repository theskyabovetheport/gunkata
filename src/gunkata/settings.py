"""Environment-resolved settings, kept apart from the schemas in types.py
because these read the environment on construction rather than being handed
their values by whatever builds them."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SuBinary(BaseSettings):
    """The su binary a device is operated through, and how to invoke it.

    Attributes:
        name: The binary to invoke on the device.
        has_dash_c: Whether this su accepts ``-c`` itself. Toybox su -- the
            AOSP default -- does not: it reads ``-c`` as the target user and
            rejects it as an invalid uid. False routes the command through
            ``su ... sh -c`` instead, which every su that can run a shell as
            the target user also supports.
        has_user: Whether this su accepts a username argument at all. False
            drops any resolved user from the command entirely.
        needs_user: Whether this su refuses to run without a username
            argument. True raises rather than silently send a command
            without one and let su fall back to whichever user it defaults
            to, which may not be the one the caller asked for.

    Design:
        Name and quirks travel together because a caller never has one
        without the other: they describe one su binary, resolved from the
        environment as a unit rather than as separate values a caller could
        drift out of sync.
    """

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    name: str = Field("su", validation_alias="GUNKATA_DEVICE_SU_BINARY")
    has_dash_c: bool = Field(
        False, validation_alias="GUNKATA_DEVICE_SU_BINARY_HAS_DASH_C"
    )
    has_user: bool = Field(True, validation_alias="GUNKATA_DEVICE_SU_BINARY_HAS_USER")
    needs_user: bool = Field(
        False, validation_alias="GUNKATA_DEVICE_SU_BINARY_NEEDS_USER"
    )

    @classmethod
    def for_device(cls, name: str | None = None) -> "SuBinary":
        """Resolve a device's su binary.

        Args:
            name: Take this name over the environment-resolved default -- an
                explicit constructor argument a caller already gave.

        Returns:
            The quirks every device shares, with name resolved by priority:
            ``name``, then the environment default.
        """
        resolved = cls()
        if name is None:
            return resolved
        return resolved.model_copy(update={"name": name})

    def wrap(self, command: str, user: str | None) -> str:
        """Build this su invocation's command line to run command as user.

        Raises:
            ValueError: needs_user is set but user is None; sending the
                command anyway would run it as whichever user su defaults
                to, not the one asked for.
        """
        if self.needs_user and user is None:
            raise ValueError(f"{self.name} needs an explicit user but none was given")
        user_part = f"{user} " if self.has_user and user is not None else ""
        shell_hop = "" if self.has_dash_c else "sh "
        return f"{self.name} {user_part}{shell_hop}-c '{command}'"
