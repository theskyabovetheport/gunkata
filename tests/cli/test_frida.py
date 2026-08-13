from typer.testing import CliRunner

from gunkata.cli import frida
from gunkata.cli.app import app

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


def test_frida_stop_renders_not_running_when_nothing_was_killed(monkeypatch):
    monkeypatch.setattr(frida, "_frida_server", lambda *a, **k: _FakeFridaServer([]))
    result = runner.invoke(app, ["frida", "stop"])
    assert result.exit_code == 0
    assert "not running" in result.output
