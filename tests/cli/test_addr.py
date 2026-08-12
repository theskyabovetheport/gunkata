from typer.testing import CliRunner

from gunkata.cli import addr
from gunkata.cli.app import app

_ADDR_MAPS = "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so\n"

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
