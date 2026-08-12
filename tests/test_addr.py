import pytest

from gunkata.addr import AddrLocator
from gunkata.procmaps_parser import ProcMapsParser


def _locator(maps_text: str) -> AddrLocator:
    return AddrLocator(ProcMapsParser(maps_text))


# Three real-shaped mappings with a gap between the first two and a gap after
# the last one -- enough to exercise contained/above/below without a live
# device.
_MAPS = (
    "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so\n"
    "7f2000-7f3000 rw-p 00000000 00:00 0 /lib/libc.so\n"
    "7f4000-7f5000 r--p 00000000 00:00 0 [anon]\n"
)


def test_constructor_rejects_a_line_without_an_address_range():
    """ProcMapsParser -- not AddrLocator itself -- owns parsing and its ValueError; see procmaps_parser.py."""
    with pytest.raises(ValueError):
        _locator("not a maps line\n")


def test_annotated_is_empty_when_nothing_was_located():
    """Mirrors grep: a pattern that matches nothing yields no output, -A/-B or not."""
    assert _locator(_MAPS).annotated() == ""


def test_contained_address_gets_offsets_from_both_of_the_mappings_edges():
    locator = _locator(_MAPS)
    locator.locate(0x7F0010)
    lines = locator.annotated().splitlines()
    assert lines[0] == (
        "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so"
        "  // contained +0x10 -0xff0"
    )
    assert lines[1] == "7f2000-7f3000 rw-p 00000000 00:00 0 /lib/libc.so"
    assert lines[2] == "7f4000-7f5000 r--p 00000000 00:00 0 [anon]"


def test_address_in_a_gap_annotates_both_bounding_mappings():
    """An address between two mappings notes 'below' on the one before it,
    with its distance past that mapping's end, and 'above' on the one after
    it, with its distance before that mapping's start."""
    locator = _locator(_MAPS)
    locator.locate(0x7F1800)  # 0x800 past the first mapping's end, 0x800 before the second's start
    lines = locator.annotated().splitlines()
    assert lines[0] == (
        "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so"
        "  // below +0x800"
    )
    assert lines[1] == (
        "7f2000-7f3000 rw-p 00000000 00:00 0 /lib/libc.so"
        "  // above -0x800"
    )
    assert lines[2] == "7f4000-7f5000 r--p 00000000 00:00 0 [anon]"


def test_address_before_the_first_mapping_only_annotates_that_mapping():
    locator = _locator(_MAPS)
    locator.locate(0x7EFF00)
    lines = locator.annotated().splitlines()
    assert lines[0] == (
        "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so"
        "  // above -0x100"
    )
    assert lines[1] == "7f2000-7f3000 rw-p 00000000 00:00 0 /lib/libc.so"


def test_address_after_the_last_mapping_only_annotates_that_mapping():
    locator = _locator(_MAPS)
    locator.locate(0x7F5100)
    lines = locator.annotated().splitlines()
    assert lines[1] == "7f2000-7f3000 rw-p 00000000 00:00 0 /lib/libc.so"
    assert lines[2] == (
        "7f4000-7f5000 r--p 00000000 00:00 0 [anon]"
        "  // below +0x100"
    )


def test_multiple_addresses_on_the_same_mapping_accumulate_notes():
    locator = _locator(_MAPS)
    locator.locate(0x7F0010)
    locator.locate(0x7F0020)
    lines = locator.annotated().splitlines()
    assert lines[0] == (
        "7f0000-7f1000 r-xp 00000000 00:00 0 /lib/libc.so"
        "  // contained +0x10 -0xff0; contained +0x20 -0xfe0"
    )


def test_locate_on_an_empty_listing_is_a_no_op():
    assert _locator("").annotated() == ""


# Six mappings so a narrow -A/-B window definitely excludes some lines,
# and two matches far enough apart that their windows can't touch.
_WIDE_MAPS = "".join(
    f"{0x1000 * i:x}-{0x1000 * (i + 1):x} r--p 00000000 00:00 0 seg{i}\n"
    for i in range(6)
)


def test_context_window_excludes_lines_outside_before_and_after():
    locator = _locator(_WIDE_MAPS)
    locator.locate(0x3000)  # contained in seg3
    lines = locator.annotated(before=1, after=1).splitlines()
    assert lines == [
        "2000-3000 r--p 00000000 00:00 0 seg2",
        "3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000",
        "4000-5000 r--p 00000000 00:00 0 seg4",
    ]


def test_context_window_of_zero_prints_only_matched_lines():
    locator = _locator(_WIDE_MAPS)
    locator.locate(0x3000)
    lines = locator.annotated(before=0, after=0).splitlines()
    assert lines == ["3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000"]


def test_distant_matches_are_separated_by_a_dashdash_marker():
    locator = _locator(_WIDE_MAPS)
    locator.locate(0x0)  # seg0
    locator.locate(0x5000)  # seg5
    lines = locator.annotated(before=0, after=0).splitlines()
    assert lines == [
        "0-1000 r--p 00000000 00:00 0 seg0  // contained +0x0 -0x1000",
        "--",
        "5000-6000 r--p 00000000 00:00 0 seg5  // contained +0x0 -0x1000",
    ]


def test_overlapping_windows_merge_without_a_separator():
    locator = _locator(_WIDE_MAPS)
    locator.locate(0x2000)  # seg2
    locator.locate(0x3000)  # seg3, one line after seg2 -- windows touch
    lines = locator.annotated(before=1, after=1).splitlines()
    assert "--" not in lines
    assert lines == [
        "1000-2000 r--p 00000000 00:00 0 seg1",
        "2000-3000 r--p 00000000 00:00 0 seg2  // contained +0x0 -0x1000",
        "3000-4000 r--p 00000000 00:00 0 seg3  // contained +0x0 -0x1000",
        "4000-5000 r--p 00000000 00:00 0 seg4",
    ]


# vdso/vsyscall, taken from a real x86_64 device: the canonical hole between
# userspace and the kernel's top-of-space vsyscall page makes the raw,
# unwrapped distance between them ~2**64 -- this pins the wrapped (shorter)
# distance instead, the one that's actually meaningful.
_CANONICAL_HOLE_MAPS = (
    "7fffc2fd7000-7fffc2fd8000 r-xp 00000000 00:00 0                          [vdso]\n"
    "ffffffffff600000-ffffffffff601000 --xp 00000000 00:00 0                  [vsyscall]\n"
)


def test_offset_wraps_to_the_shorter_distance_across_the_canonical_hole():
    """The raw difference here is ~2**64; the wrapped distance -- going the
    other way around the 64-bit address ring -- is ~0x7fffc39d8000. Direction
    still comes from the raw delta's own sign: going the short way round
    doesn't put address on the other side of either edge."""
    locator = _locator(_CANONICAL_HOLE_MAPS)
    locator.locate(0x7FFFC2FD7000 + 0x1000)  # exactly vdso's end: the gap starts here
    lines = locator.annotated(before=0, after=0).splitlines()
    assert lines == [
        "7fffc2fd7000-7fffc2fd8000 r-xp 00000000 00:00 0"
        "                          [vdso]  // below +0x0",
        "ffffffffff600000-ffffffffff601000 --xp 00000000 00:00 0"
        "                  [vsyscall]  // above -0x7fffc39d8000",
    ]


def test_relative_offset_is_a_no_op_for_ordinary_small_gaps():
    """Guards the fix above from ever kicking in on a normal-sized delta:
    for any realistic gap the wrapped distance is astronomically larger than
    the raw one, so min() must keep picking the raw, unwrapped magnitude."""
    assert AddrLocator._relative(0x800) == "+0x800"
    assert AddrLocator._relative(-0x800) == "-0x800"
