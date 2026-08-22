import importlib
import subprocess

import pytest
import typer
from typer.testing import CliRunner

from gunkata.cli import mem
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")


def test_parse_mem_address_expr_delegates_to_the_shared_parser():
    """The grammar itself is pinned once, in test_hexaddr.py; this only
    guards mem's own wiring to it."""
    assert mem._parse_mem_address_expr("0x1000+0x10") == 0x1010


def test_parse_mem_address_expr_turns_a_parse_failure_into_a_loud_exit():
    with pytest.raises(typer.Exit):
        mem._parse_mem_address_expr("not-hex")


class _MemFakeAdb:
    """Answers `command -v su`, `pidof`, the maps read_file wrapper, and `dd` canned."""

    def __init__(
        self,
        maps: bytes,
        dd_stdout: bytes = b"",
        dd_ok: bool = True,
        pidof_output: str = "",
    ):
        self.serial = "fake-serial"
        self._maps = maps
        self._dd_stdout = dd_stdout
        self._dd_ok = dd_ok
        self._pidof_output = pidof_output
        self.calls: list[list[str]] = []
        self.last_input: bytes | None = None

    def __call__(self, args, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        command = args[-1] if args and args[0] == "shell" else ""
        if "command -v" in command:
            return subprocess.CompletedProcess(args, 0, b"/system/bin/su\n", b"")
        if "pidof" in command:
            return subprocess.CompletedProcess(
                args, 0, self._pidof_output.encode(), b""
            )
        if "maps" in command:
            return subprocess.CompletedProcess(args, 0, self._maps, b"")
        if "dd " in command:
            self.last_input = kwargs.get("input")
            returncode = 0 if self._dd_ok else 1
            return subprocess.CompletedProcess(args, returncode, self._dd_stdout, b"")
        raise AssertionError(f"unexpected command: {command!r}")


_MEM_MAPS = b"7f0000000000-7f0000010000 rw-p 00000000 00:00 0\n"


def test_mem_read_writes_raw_bytes_to_stdout_when_piped(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hello")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "read", "-s", "0x7f0000000000", "-e", "0x7f0000000005", "-p", "1234"],
    )
    assert result.exit_code == 0
    assert result.output == "hello"


def test_mem_read_hexdumps_when_stdout_is_a_tty(monkeypatch, capsys):
    """CliRunner swaps sys.stdout for its own stream, defeating an isatty patch made
    beforehand (see test_ps.py's tty tests for the same reason); calling mem_read()
    directly sidesteps it."""
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hi")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    monkeypatch.setattr(mem.sys.stdout, "isatty", lambda: True)
    mem.mem_read(start="0x7f0000000000", end="0x7f0000000002", pid=1234, name=None)
    out = capsys.readouterr().out
    assert "68 69" in out
    assert "hi" in out


def test_mem_read_requires_exactly_one_of_p_or_capital_p():
    result = CliRunner().invoke(app, ["mem", "read", "-s", "0x1", "-e", "0x2"])
    assert result.exit_code == 2
    assert "pass exactly one of -p/-P" in result.output


def test_mem_read_with_capital_p_resolves_the_name_to_a_pid(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, dd_stdout=b"hello", pidof_output="1234\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "read", "-s", "0x7f0000000000", "-e", "0x7f0000000005", "-P", "com.example.app"],
    )
    assert result.exit_code == 0
    assert result.output == "hello"


def test_mem_read_rejects_both_p_and_capital_p():
    result = CliRunner().invoke(
        app,
        ["mem", "read", "-s", "0x1", "-e", "0x2", "-p", "1234", "-P", "com.example.app"],
    )
    assert result.exit_code == 2


def test_mem_read_with_capital_p_errors_when_name_matches_multiple_processes(
    monkeypatch,
):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="1234 5678\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "read", "-s", "0x1", "-e", "0x2", "-P", "com.example.app"],
    )
    assert result.exit_code == 1


def test_mem_read_with_capital_p_errors_when_name_matches_nothing(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "read", "-s", "0x1", "-e", "0x2", "-P", "no.such.app"],
    )
    assert result.exit_code == 1


def test_mem_read_rejects_an_unparseable_address():
    result = CliRunner().invoke(
        app, ["mem", "read", "-s", "zz", "-e", "0x2", "-p", "1234"]
    )
    assert result.exit_code == 2


def test_mem_read_reports_an_unmapped_range_loudly(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app, ["mem", "read", "-s", "0x1", "-e", "0x10", "-p", "1234"]
    )
    assert result.exit_code == 1
    assert "not fully mapped" in result.output


def test_mem_write_sends_stdins_bytes(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "write", "-s", "0x7f0000000000", "-p", "1234"],
        input=b"payload",
    )
    assert result.exit_code == 0
    assert fake.last_input == b"payload"


def test_mem_write_with_capital_p_resolves_the_name_to_a_pid(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="1234\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "write", "-s", "0x7f0000000000", "-P", "com.example.app"],
        input=b"payload",
    )
    assert result.exit_code == 0
    assert fake.last_input == b"payload"


def test_mem_write_requires_exactly_one_of_p_or_capital_p():
    result = CliRunner().invoke(app, ["mem", "write", "-s", "0x7f0000000000"])
    assert result.exit_code == 2
    assert "pass exactly one of -p/-P" in result.output


def test_mem_write_rejects_both_p_and_capital_p():
    result = CliRunner().invoke(
        app,
        [
            "mem", "write", "-s", "0x7f0000000000",
            "-p", "1234", "-P", "com.example.app",
        ],
    )
    assert result.exit_code == 2


def test_mem_write_with_capital_p_errors_when_name_matches_multiple_processes(
    monkeypatch,
):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="1234 5678\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "write", "-s", "0x7f0000000000", "-P", "com.example.app"],
    )
    assert result.exit_code == 1


def test_mem_write_with_capital_p_errors_when_name_matches_nothing(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS, pidof_output="")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "write", "-s", "0x7f0000000000", "-P", "no.such.app"],
    )
    assert result.exit_code == 1


def test_mem_write_rejects_data_that_would_cross_the_given_end(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app,
        ["mem", "write", "-s", "0x7f0000000000", "-e", "0x7f0000000005", "-p", "1234"],
        input=b"0123456789",
    )
    assert result.exit_code == 1


def test_mem_write_reports_an_unmapped_range_loudly(monkeypatch):
    fake = _MemFakeAdb(maps=_MEM_MAPS)
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app, ["mem", "write", "-s", "0x1", "-p", "1234"], input=b"x"
    )
    assert result.exit_code == 1
    assert "not fully mapped" in result.output
