import logging

import pytest

from gunkata.cli.logging_config import LogSettings, configure_logging


def test_level_defaults_to_warning(monkeypatch):
    """GUNKATA_LOG_LEVEL unset must default to WARNING, not logging's own
    unconfigured default (which is effectively the same value today, but
    only because nobody chose otherwise)."""
    monkeypatch.delenv("GUNKATA_LOG_LEVEL", raising=False)
    assert LogSettings.from_env().level == logging.WARNING


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("DEBUG", logging.DEBUG),
        ("debug", logging.DEBUG),
        ("Info", logging.INFO),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_level_accepts_literal_names(monkeypatch, raw, expected):
    monkeypatch.setenv("GUNKATA_LOG_LEVEL", raw)
    assert LogSettings.from_env().level == expected


@pytest.mark.parametrize("raw, expected", [("10", 10), ("20", 20), ("5", 5)])
def test_level_accepts_numbers(monkeypatch, raw, expected):
    monkeypatch.setenv("GUNKATA_LOG_LEVEL", raw)
    assert LogSettings.from_env().level == expected


def test_level_rejects_unknown_value(monkeypatch):
    """A typo must raise loudly, never silently fall back to a default the
    caller never asked for."""
    monkeypatch.setenv("GUNKATA_LOG_LEVEL", "not-a-level")
    with pytest.raises(ValueError, match="not-a-level"):
        LogSettings.from_env()


def test_configure_logging_sets_root_logger_level(monkeypatch):
    monkeypatch.setenv("GUNKATA_LOG_LEVEL", "DEBUG")
    root = logging.getLogger()
    previous_level = root.level
    previous_handlers = list(root.handlers)
    try:
        root.handlers.clear()
        configure_logging()
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(previous_level)
        root.handlers[:] = previous_handlers


def test_configure_logging_wins_over_a_preexisting_handler(monkeypatch):
    """A handler installed before configure_logging runs (an import side
    effect, or pytest's own logging capture) must not make basicConfig a
    silent no-op -- this is the one place that configures logging at all."""
    monkeypatch.setenv("GUNKATA_LOG_LEVEL", "DEBUG")
    root = logging.getLogger()
    previous_level = root.level
    previous_handlers = list(root.handlers)
    try:
        root.handlers.clear()
        root.addHandler(logging.NullHandler())
        configure_logging()
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(previous_level)
        root.handlers[:] = previous_handlers
