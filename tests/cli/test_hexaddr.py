import pytest

from gunkata.cli.hexaddr import parse_hex_address_expr


def test_accepts_a_bare_hex_term():
    assert parse_hex_address_expr("0x7f0500") == 0x7F0500


def test_accepts_a_term_without_a_0x_prefix():
    assert parse_hex_address_expr("7f0500") == 0x7F0500


def test_sums_a_plus_joined_offset():
    assert parse_hex_address_expr("0x7f0000+0x500") == 0x7F0500


def test_subtracts_a_minus_joined_offset():
    assert parse_hex_address_expr("0x7f0500-0x500") == 0x7F0000


def test_chains_multiple_offsets_in_order():
    assert parse_hex_address_expr("0x7f0000+0x600-0x100") == 0x7F0000 + 0x600 - 0x100


def test_rejects_an_empty_expression():
    with pytest.raises(ValueError):
        parse_hex_address_expr("")


def test_rejects_a_non_hex_term():
    with pytest.raises(ValueError):
        parse_hex_address_expr("0x1000+zz")
