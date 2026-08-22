"""`gunkata`'s root callback: -s/-U/-C, the CLI's global options."""

import importlib
import os
import subprocess

from typer.testing import CliRunner

from gunkata.cli import pull  # noqa: F401 -- imported for its command registration
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


class _AppFakeAdb:
    """Answers `pull`'s file probe, then `cat <dpath>`, canned -- just enough
    for a subcommand to complete so a test can check the env side effect the
    root callback should already have produced by then.
    """

    def __init__(self):
        self.serial = "fake-serial"

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        if "stdout" not in kwargs:
            return subprocess.CompletedProcess(args, 0, b"f", b"")
        kwargs["stdout"].write(b"payload")
        return subprocess.CompletedProcess(args, 0, b"", b"")


def test_root_serial_option_sets_android_serial_before_the_subcommand_runs(
    monkeypatch, tmp_path
):
    """`gunkata -s <serial> ...` must set $ANDROID_SERIAL before the
    subcommand's own bare `Adb()` runs: no subcommand takes a serial option
    of its own, so the root callback is the one place a serial reaches
    Adb.__init__'s own env-var check.

    The root callback writes straight to the real os.environ (see app.py's
    Design note), so monkeypatch never learns of that write and can't revert
    it on teardown the way it does its own setenv/delenv calls -- this test
    pops the key back out itself rather than leaking a fake serial into
    every test that runs after it in this same process.
    """
    monkeypatch.delenv("ANDROID_SERIAL", raising=False)
    seen = []

    def _fake_adb(*args, **kwargs):
        seen.append(os.environ.get("ANDROID_SERIAL"))
        return _AppFakeAdb()

    monkeypatch.setattr(device_mod, "Adb", _fake_adb)
    monkeypatch.chdir(tmp_path)
    try:
        result = CliRunner().invoke(
            app, ["-s", "emulator-9999", "pull", "/data/local/tmp/foo.bin"]
        )
        assert result.exit_code == 0
        assert seen == ["emulator-9999"]
    finally:
        os.environ.pop("ANDROID_SERIAL", None)


def test_root_user_option_sets_the_default_user_env_var_before_the_subcommand_runs(
    monkeypatch, tmp_path
):
    """`gunkata -U <user> ...` must set $GUNKATA_SHELL_DEFAULT_USER before the
    subcommand resolves its Shell: no subcommand carries its own -U/--user
    option; see `Device.shell`'s docstring.

    Popped back out in a finally, for the same reason as the -s test above.
    """
    monkeypatch.delenv("GUNKATA_SHELL_DEFAULT_USER", raising=False)
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _AppFakeAdb())
    monkeypatch.chdir(tmp_path)
    try:
        result = CliRunner().invoke(
            app, ["-U", "root", "pull", "/data/local/tmp/foo.bin"]
        )
        assert result.exit_code == 0
        assert os.environ["GUNKATA_SHELL_DEFAULT_USER"] == "root"
    finally:
        os.environ.pop("GUNKATA_SHELL_DEFAULT_USER", None)


def test_root_options_are_absent_by_default(monkeypatch, tmp_path):
    """Without -s/-U, the root callback must leave both env vars untouched --
    a bare `gunkata pull` must behave exactly as it did before either option
    existed."""
    monkeypatch.delenv("ANDROID_SERIAL", raising=False)
    monkeypatch.delenv("GUNKATA_SHELL_DEFAULT_USER", raising=False)
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: _AppFakeAdb())
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["pull", "/data/local/tmp/foo.bin"])
    assert result.exit_code == 0
    assert "ANDROID_SERIAL" not in os.environ
    assert "GUNKATA_SHELL_DEFAULT_USER" not in os.environ
