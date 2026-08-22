import pytest
from typer.testing import CliRunner

from gunkata.cli import frida
from gunkata.cli.app import app
from gunkata.common.download import BinaryDownloadError
from gunkata.frida.repo import (
    ServerAssetError,
    UnsupportedAbiError,
    VersionUnresolvedError,
)

runner = CliRunner()


class _FakeFridaServer:
    def __init__(self, pids):
        self._pids = pids

    def start(self):
        return self._pids

    def stop(self):
        return self._pids

    def running_pids(self):
        return self._pids


def test_frida_help_lists_start_stop_status():
    result = runner.invoke(app, ["frida", "--help"])
    assert result.exit_code == 0
    for name in ("start", "stop", "status"):
        assert name in result.output


def test_frida_status_running_exits_zero(monkeypatch):
    monkeypatch.setattr(frida, "_frida_server", lambda *a, **k: _FakeFridaServer([42]))
    result = runner.invoke(app, ["frida", "status"])
    assert result.exit_code == 0
    assert "42" in result.output


def test_frida_status_stopped_exits_one(monkeypatch):
    monkeypatch.setattr(frida, "_frida_server", lambda *a, **k: _FakeFridaServer([]))
    result = runner.invoke(app, ["frida", "status"])
    assert result.exit_code == 1


def test_frida_start_renders_the_pids(monkeypatch):
    monkeypatch.setattr(frida, "_frida_server", lambda *a, **k: _FakeFridaServer([7]))
    result = runner.invoke(app, ["frida", "start"])
    assert result.exit_code == 0
    assert "7" in result.output


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (VersionUnresolvedError, "frida is not installed, so no default"),
        (UnsupportedAbiError, "no frida android build for abi 'mips'"),
        (ServerAssetError, "no frida-server-1.2.3-android-arm64.xz in frida repo"),
        (BinaryDownloadError, "fetching frida-server from GitHub failed"),
    ],
)
def test_frida_start_reports_a_provisioning_failure_without_a_traceback(
    monkeypatch, error, message
):
    """Failing to provision a binary is a user-fixable condition, not a crash.

    Each of these carries the fix in its own message -- pass a version, place the
    archive in the repo, retry the download. The command must exit 1 rendering
    that message, since a stack dump buries the one line the user needs.
    """

    class _Unprovisionable:
        def start(self):
            raise error(message)

    monkeypatch.setattr(frida, "_frida_server", lambda *a, **k: _Unprovisionable())
    result = runner.invoke(app, ["frida", "start"])
    assert result.exit_code == 1
    assert message in result.output
    assert "Traceback" not in result.output


def test_frida_stop_renders_not_running_when_nothing_was_killed(monkeypatch):
    monkeypatch.setattr(frida, "_frida_server", lambda *a, **k: _FakeFridaServer([]))
    result = runner.invoke(app, ["frida", "stop"])
    assert result.exit_code == 0
    assert "not running" in result.output
