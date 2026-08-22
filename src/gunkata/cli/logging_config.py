"""Root logger configuration for the `gunkata` CLI, resolved from $GUNKATA_LOG_LEVEL.

`configure_logging` is called exactly once, from the CLI entry point
(`gunkata.cli.main:main`), before any subcommand runs -- per CLAUDE.md's
Logging section, a module logs, only the application configures. This is the
CLI acting as that application; library callers configure the `"gunkata"`
logger themselves and must never call `configure_logging`, since it reaches
past gunkata's own logger hierarchy to the real root logger.

`LogSettings` lives here rather than at the package root because
`configure_logging` is its only consumer -- per CLAUDE.md's settings-class
rule, a settings class colocates with its sole consumer.
"""

import logging

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogSettings(BaseSettings):
    """A logger level, resolved from the environment.

    Attributes:
        level: The numeric level `$GUNKATA_LOG_LEVEL` names, or WARNING if unset.
    """

    model_config = SettingsConfigDict(populate_by_name=True, frozen=True)

    level: int = Field(logging.WARNING, validation_alias="GUNKATA_LOG_LEVEL")

    @field_validator("level", mode="before")
    @classmethod
    def _resolve_level(cls, value: object) -> int:
        """Accept a level number or a level name, case-insensitively.

        Returns:
            The resolved numeric level.

        Raises:
            ValueError: value is neither an integer nor a name logging
                recognizes.
        """
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if text.lstrip("-").isdigit():
            return int(text)
        names = logging.getLevelNamesMapping()
        try:
            return names[text.upper()]
        except KeyError:
            raise ValueError(
                f"GUNKATA_LOG_LEVEL={value!r} is not a valid level name or "
                f"number; expected an integer or one of {sorted(names)}"
            ) from None

    @classmethod
    def from_env(cls) -> "LogSettings":
        return cls()


def configure_logging() -> None:
    """Set the root logger's level from $GUNKATA_LOG_LEVEL, default WARNING.

    Design:
        ``force=True``: ``logging.basicConfig`` otherwise does nothing --
        not even the level -- once the root logger already has a handler,
        which anything imported ahead of this call (or a test harness) may
        already have installed. This is the one place that configures
        logging at all, so it must win over whatever ran first, not defer
        to it silently.
    """
    logging.basicConfig(level=LogSettings.from_env().level, force=True)
