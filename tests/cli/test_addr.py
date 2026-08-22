import importlib
import subprocess

from typer.testing import CliRunner

from gunkata.cli import addr
from gunkata.cli.app import app

# The `gunkata.device` attribute is the package's device() factory function,
# which shadows the submodule of the same name, so it has to be imported by name.
device_mod = importlib.import_module("gunkata.device")

_ADDR_MAPS = "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so\n"
_ADDR_MAPS_BYTES = _ADDR_MAPS.encode()


class _AddrFakeAdb:
    """Answers `command -v su`, `pidof`, and the maps read_file wrapper."""

    def __init__(self, maps: bytes = _ADDR_MAPS_BYTES, pidof_output: str = ""):
        self.serial = "fake-serial"
        self._maps = maps
        self._pidof_output = pidof_output
        self.calls: list[list[str]] = []

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
        raise AssertionError(f"unexpected command: {command!r}")

_ADDR_MAPS_WIDE = (
    "1000-2000 r--p 00000000 00:00 0 seg1\n"
    "2000-3000 r--p 00000000 00:00 0 seg2\n"
    "3000-4000 r--p 00000000 00:00 0 seg3\n"
    "4000-5000 r--p 00000000 00:00 0 seg4\n"
    "5000-6000 r--p 00000000 00:00 0 seg5\n"
)


def test_addr_annotates_the_piped_listing_with_the_located_address():
    result = CliRunner().invoke(app, ["addr", "0x7f0000+0x10"], input=_ADDR_MAPS)
    assert result.exit_code == 0
    assert result.output == (
        "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so  // contained +0x10 -0xff0\n"
    )


def test_addr_supports_minus_terms_in_the_address_expression():
    result = CliRunner().invoke(app, ["addr", "0x7f0020-0x10"], input=_ADDR_MAPS)
    assert result.exit_code == 0
    assert "contained +0x10 -0xff0" in result.output


def test_addr_defaults_to_three_lines_of_context_on_each_side():
    result = CliRunner().invoke(app, ["addr", "0x3000"], input=_ADDR_MAPS_WIDE)
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "1000-2000 r--p 00000000 00:00 0 seg1",
        "2000-3000 r--p 00000000 00:00 0 seg2",
        "3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000",
        "4000-5000 r--p 00000000 00:00 0 seg4",
        "5000-6000 r--p 00000000 00:00 0 seg5",
    ]


def test_addr_a_and_b_narrow_the_context_window():
    result = CliRunner().invoke(
        app, ["addr", "0x3000", "-A", "0", "-B", "1"], input=_ADDR_MAPS_WIDE
    )
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "2000-3000 r--p 00000000 00:00 0 seg2",
        "3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000",
    ]


def test_addr_requires_the_address_argument():
    result = CliRunner().invoke(app, ["addr"], input=_ADDR_MAPS)
    assert result.exit_code == 2


def test_addr_rejects_an_unparseable_address():
    result = CliRunner().invoke(app, ["addr", "not-hex"], input=_ADDR_MAPS)
    assert result.exit_code == 2


def test_addr_rejects_a_malformed_maps_line():
    result = CliRunner().invoke(app, ["addr", "0x7f0000"], input="not a maps line\n")
    assert result.exit_code == 1


def test_addr_errors_when_stdin_is_a_tty(monkeypatch):
    monkeypatch.setattr(addr, "stdin_is_tty", lambda: True)
    result = CliRunner().invoke(app, ["addr", "0x7f0000"], input=_ADDR_MAPS)
    assert result.exit_code == 1
    assert "pipe" in result.output


def test_addr_with_p_fetches_the_pids_own_maps(monkeypatch):
    """-p must never touch stdin -- CliRunner's default (empty) stdin would
    otherwise be read as an (empty, malformed) maps listing."""
    fake = _AddrFakeAdb()
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["addr", "0x7f0000+0x10", "-p", "1234"])
    assert result.exit_code == 0
    assert "contained +0x10 -0xff0" in result.output


def test_addr_with_capital_p_resolves_the_name_to_a_pid(monkeypatch):
    fake = _AddrFakeAdb(pidof_output="1234\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app, ["addr", "0x7f0000+0x10", "-P", "com.example.app"]
    )
    assert result.exit_code == 0
    assert "contained +0x10 -0xff0" in result.output


def test_addr_rejects_both_p_and_capital_p():
    result = CliRunner().invoke(
        app, ["addr", "0x7f0000", "-p", "1234", "-P", "com.example.app"]
    )
    assert result.exit_code == 2


def test_addr_with_capital_p_errors_when_name_matches_multiple_processes(monkeypatch):
    fake = _AddrFakeAdb(pidof_output="1234 5678\n")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(
        app, ["addr", "0x7f0000", "-P", "com.example.app"]
    )
    assert result.exit_code == 1


def test_addr_with_capital_p_errors_when_name_matches_nothing(monkeypatch):
    fake = _AddrFakeAdb(pidof_output="")
    monkeypatch.setattr(device_mod, "Adb", lambda *a, **k: fake)
    result = CliRunner().invoke(app, ["addr", "0x7f0000", "-P", "no.such.app"])
    assert result.exit_code == 1


def test_addr_with_p_rejects_an_unparseable_address():
    result = CliRunner().invoke(app, ["addr", "not-hex", "-p", "1234"])
    assert result.exit_code == 2
