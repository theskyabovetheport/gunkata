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


@pytest.fixture
def device() -> Device:
    """A Device bound to the sole live adb-attached serial. Emulator tests only."""
    return Device(Adb())
