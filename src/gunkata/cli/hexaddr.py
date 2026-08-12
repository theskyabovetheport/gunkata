"""Address-expression parsing shared by commands that take one (addr, mem)."""

import re

_TERM = re.compile(r"[+-]?[^+-]+")


def parse_hex_address_expr(expr: str) -> int:
    """Resolve an ADDR{+-}OFFSET{+-}OFFSET... expression to an integer address.

    Args:
        expr: A base address in hex, followed by any number of chained
            +offset/-offset terms, each hex the same way -- e.g. "7f0000",
            "0x7f0000+0x10", "0x7f0000+0x100-0x10". An "0x" prefix is
            accepted but not required, matching the bare hex
            /proc/<pid>/maps prints, so an address copied straight from it
            needs no editing.

    Returns:
        The base address with every chained offset applied in order.

    Raises:
        ValueError: expr is empty, or a term isn't a valid hex integer.
    """
    terms = _TERM.findall(expr.strip())
    if not terms:
        raise ValueError(f"empty address expression: {expr!r}")
    addr = int(terms[0], 16)
    for term in terms[1:]:
        sign = -1 if term[0] == "-" else 1
        addr += sign * int(term[1:] if term[0] in "+-" else term, 16)
    return addr
