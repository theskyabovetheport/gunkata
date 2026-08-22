"""TarExtractor: safety rules for extracting a streamed tar archive, tested
against plain BytesIO archives so nothing here touches a subprocess.
"""

import io
import os
import tarfile

import pytest

from gunkata.tarextract import TarExtractor


def _archive(members: list[tuple[tarfile.TarInfo, bytes | None]]) -> tarfile.TarFile:
    """Build an open, readable TarFile in memory from (TarInfo, data) pairs.

    data is None for a member with no content of its own (a directory, a
    symlink, or a synthetic device node).
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as writer:
        for info, data in members:
            writer.addfile(info, io.BytesIO(data) if data is not None else None)
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r|", errorlevel=1)


def _file_member(name: str, data: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def _dir_member(name: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755  # TarInfo defaults to 0o644, which lacks the execute
    # bit a real directory needs to be traversable into.
    return info, None


def _symlink_member(name: str, target: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.SYMTYPE
    info.linkname = target
    return info, None


def _device_member(name: str) -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = tarfile.CHRTYPE
    info.devmajor = 1
    info.devminor = 3
    return info, None


def test_extracts_a_tree_under_the_destination(tmp_path):
    archive = _archive(
        [_dir_member("d"), _file_member("d/a.txt", b"hello"), _file_member("d/b.txt", b"world")]
    )
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    assert (tmp_path / "d" / "a.txt").read_bytes() == b"hello"
    assert (tmp_path / "d" / "b.txt").read_bytes() == b"world"


def test_records_paths_in_archive_order(tmp_path):
    archive = _archive(
        [_dir_member("d"), _file_member("d/a.txt", b"1"), _file_member("d/b.txt", b"2")]
    )
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    assert extractor.paths == [
        str(tmp_path / "d"),
        str(tmp_path / "d" / "a.txt"),
        str(tmp_path / "d" / "b.txt"),
    ]


def test_reports_where_a_renamed_member_actually_landed(tmp_path):
    """data_filter accepts an absolute member name by stripping its leading
    separator rather than refusing it, so the landed path must come from the
    filtered member. Deriving it from the archive's own name would report a
    path outside the destination -- os.path.join drops the destination
    entirely when handed an absolute second argument, naming a real system
    file the pull never wrote."""
    archive = _archive([_file_member("/etc/passwd", b"payload")])
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    assert (tmp_path / "etc" / "passwd").read_bytes() == b"payload"
    assert extractor.paths == [str(tmp_path / "etc" / "passwd")]
    assert extractor.skipped == []


def test_skips_and_names_an_absolute_symlink(tmp_path):
    """Android app dirs routinely hold one (lib -> /data/app/.../lib/arm64);
    the safe filter refuses it rather than aborting the whole extraction."""
    archive = _archive([_symlink_member("lib", "/data/app/pkg/lib/arm64")])
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    assert extractor.paths == []
    assert extractor.skipped == ["lib"]


def test_skips_a_member_escaping_the_destination(tmp_path):
    archive = _archive([_file_member("../escape.txt", b"x")])
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    assert extractor.paths == []
    assert extractor.skipped == ["../escape.txt"]
    assert not (tmp_path.parent / "escape.txt").exists()


def test_skips_a_device_node(tmp_path):
    """toybox tar archives /dev/null's character-device entry; stock
    filter="data" would raise SpecialFileError and abort the whole pull."""
    archive = _archive([_device_member("dev/null")])
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    assert extractor.paths == []
    assert extractor.skipped == ["dev/null"]


def test_keeps_the_setuid_bit_and_the_devices_mode(tmp_path):
    """Pins why stock filter="data" was not used as-is: it clamps mode to
    & 0o755 and strips higher bits, which would silently drop a setuid bit a
    researcher pulled the tree specifically to see."""
    info, data = _file_member("suid.bin", b"x")
    info.mode = 0o104755  # regular file, setuid, rwxr-xr-x
    archive = _archive([(info, data)])
    extractor = TarExtractor(str(tmp_path))
    extractor.extract_all(archive)
    landed = tmp_path / "suid.bin"
    assert landed.exists()
    assert (os.stat(landed).st_mode & 0o7777) == 0o4755


def test_keeps_what_landed_when_the_stream_breaks_mid_member(tmp_path):
    """A truncated stream must not discard members that fully arrived
    before the break -- this is what makes per-member extraction, not
    extractall, worth the extra code."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as writer:
        for name, data in [("a.txt", b"hello"), ("b.txt", b"X" * 2000)]:
            info, content = _file_member(name, data)
            writer.addfile(info, io.BytesIO(content))
    raw = buf.getvalue()
    # Cuts off partway through b.txt's data block, after a.txt landed
    # completely and b.txt's header was read in full.
    truncated = raw[: 1536 + 200]
    extractor = TarExtractor(str(tmp_path))
    with (
        tarfile.open(fileobj=io.BytesIO(truncated), mode="r|", errorlevel=1) as archive,
        pytest.raises(tarfile.TarError),
    ):
        extractor.extract_all(archive)
    assert extractor.paths == [str(tmp_path / "a.txt")]
    assert (tmp_path / "a.txt").read_bytes() == b"hello"
