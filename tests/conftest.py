import pytest

from gunkata.adb import Adb, AdbError
from gunkata.device import Device


def pytest_collection_modifyitems(config, items):
    """Skip emulator-marked tests when no device is attached.

    Without this they raise AdbError at setup and report as errors, which reads
    as a broken suite rather than as tests that never had the hardware to run.
    """
    if _attached_serial() is not None:
        return
    skip = pytest.mark.skip(reason="no adb device attached")
    for item in items:
        if "emulator" in item.keywords:
            item.add_marker(skip)


def _attached_serial() -> str | None:
    """The sole attached serial, or nothing when there is not exactly one.

    Returns:
        The serial every emulator test will run against, or nothing when adb is
        absent, reports no device, or reports more than one.
    """
    try:
        return Adb().serial
    except (AdbError, FileNotFoundError):
        return None


@pytest.fixture(autouse=True)
def isolated_gunkata_root(tmp_path, monkeypatch):
    """Point GUNKATA_ROOT at an empty directory for every test.

    Device resolves its su configuration from the settings persisted under
    GUNKATA_ROOT, so without this a developer who has run `gunkata device env
    --edit` to set GUNKATA_SHELL_DEFAULT_USER=root against their own emulator
    would see this suite's default-user assertions flip -- the tests would
    pass or fail depending on whose machine ran them.
    """
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path / "gunkata-root"))


@pytest.fixture
def device() -> Device:
    """A Device bound to the sole live adb-attached serial. Emulator tests only."""
    return Device()
