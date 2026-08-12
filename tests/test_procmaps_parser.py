import pytest

from gunkata.procmaps_parser import MemoryMapping, ProcMapsParser

_MAPS = (
    "7f0000-7f1000 r-xp 00001000 08:01 131099 /lib/libc.so\n"
    "7f2000-7f3000 rw-p 00000000 00:00 0 [anon]\n"
    "7f4000-7f5000 r--p 00000000 00:00 0\n"
)


def test_mappings_parses_every_field_of_a_line_with_a_pathname():
    mapping = ProcMapsParser(_MAPS).mappings()[0]
    assert mapping == MemoryMapping(
        line="7f0000-7f1000 r-xp 00001000 08:01 131099 /lib/libc.so",
        start=0x7F0000,
        end=0x7F1000,
        perms="r-xp",
        offset=0x1000,
        dev="08:01",
        inode=131099,
        pathname="/lib/libc.so",
    )


def test_mappings_defaults_pathname_to_empty_when_a_line_has_none():
    mapping = ProcMapsParser(_MAPS).mappings()[2]
    assert mapping.pathname == ""


def test_mappings_preserves_listing_order():
    parser = ProcMapsParser(_MAPS)
    assert [m.start for m in parser.mappings()] == [0x7F0000, 0x7F2000, 0x7F4000]


def test_mappings_skips_blank_lines():
    assert ProcMapsParser("\n" + _MAPS + "\n").mappings() == ProcMapsParser(_MAPS).mappings()


def test_constructor_rejects_a_line_that_does_not_match_the_maps_format():
    with pytest.raises(ValueError):
        ProcMapsParser("not a maps line\n")


def test_find_returns_the_mapping_containing_address():
    parser = ProcMapsParser(_MAPS)
    assert parser.find(0x7F0010).pathname == "/lib/libc.so"


def test_find_returns_none_for_an_address_in_a_gap():
    assert ProcMapsParser(_MAPS).find(0x7F1800) is None


def test_find_returns_none_for_an_address_past_every_mapping():
    assert ProcMapsParser(_MAPS).find(0x800000) is None


def test_index_of_returns_the_mappings_position_in_listing_order():
    parser = ProcMapsParser(_MAPS)
    mappings = parser.mappings()
    assert parser.index_of(mappings[2]) == 2


def test_index_of_raises_for_a_mapping_not_from_this_parser():
    parser = ProcMapsParser(_MAPS)
    foreign = ProcMapsParser("1000-2000 r--p 00000000 00:00 0 x\n").mappings()[0]
    with pytest.raises(ValueError):
        parser.index_of(foreign)
