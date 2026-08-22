import hashlib
import tarfile
import urllib.error
from pathlib import Path

import pytest

from gunkata.scrcpy import repo as repo_mod
from gunkata.scrcpy.repo import (
    HostArch,
    ScrcpyAssetError,
    ScrcpyChecksumError,
    ScrcpyRepo,
    UnsupportedHostError,
)
from gunkata.scrcpy.settings import ScrcpySettings


def _make_archive(tmp_path: Path, arch: HostArch, version: str, payload: bytes) -> bytes:
    """Build a scrcpy-shaped tar.gz: one top-level dir with scrcpy/scrcpy-server."""
    top = f"scrcpy-{arch.value}-v{version}"
    src = tmp_path / "src"
    (src / top).mkdir(parents=True)
    (src / top / "scrcpy").write_bytes(payload)
    (src / top / "scrcpy-server").write_bytes(b"SERVER")
    archive_path = tmp_path / f"{top}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(src / top, arcname=top)
    return archive_path.read_bytes()


class _FakeDownloader:
    """Writes canned bytes to dest for a given URL, instead of touching the network."""

    def __init__(self, by_url: dict[str, bytes]):
        self._by_url = by_url
        self.calls: list[str] = []

    def download(self, url, dest):
        self.calls.append(url)
        dest.write_bytes(self._by_url[url])


def test_an_unsupported_host_is_refused(monkeypatch):
    """A host that is not Linux/x86_64 gets a refusal naming what it actually is,
    since Xephyr -- the whole mechanism this feature relies on -- is X11-only."""
    monkeypatch.setattr(repo_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(repo_mod.platform, "machine", lambda: "arm64")
    with pytest.raises(UnsupportedHostError) as exc:
        HostArch.from_platform()
    assert "Darwin" in str(exc.value)
    assert "arm64" in str(exc.value)


def test_linux_x86_64_and_amd64_both_resolve(monkeypatch):
    monkeypatch.setattr(repo_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(repo_mod.platform, "machine", lambda: "AMD64")
    assert HostArch.from_platform() is HostArch.linux_x86_64


def test_a_bad_version_token_is_refused(tmp_path):
    repo = ScrcpyRepo(tmp_path)
    with pytest.raises(ValueError):
        repo.resolve(version="4.1.0-rc1")


def test_a_missing_archive_names_the_autodownload_variable(tmp_path):
    """With autodownload off (its default), a missing archive is refused with a
    message naming both where it should be placed and the env var to set instead."""
    repo = ScrcpyRepo(tmp_path)
    with pytest.raises(ScrcpyAssetError) as exc:
        repo.resolve(version="4.1")
    message = str(exc.value)
    assert "scrcpy-linux-x86_64-v4.1.tar.gz" in message
    assert "GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY" in message


def test_resolve_extracts_a_locally_placed_archive(tmp_path):
    """An archive already sitting in the repo is extracted without any network
    access, autodownload on or off."""
    payload = _make_archive(tmp_path, HostArch.linux_x86_64, "4.1", b"BINARY")
    (tmp_path / "scrcpy-linux-x86_64-v4.1.tar.gz").write_bytes(payload)
    repo = ScrcpyRepo(tmp_path)
    binary = repo.resolve(version="4.1")
    assert binary == tmp_path / "scrcpy-linux-x86_64-v4.1" / "scrcpy"
    assert binary.read_bytes() == b"BINARY"
    assert (binary.parent / "scrcpy-server").read_bytes() == b"SERVER"


def test_a_second_resolve_does_not_re_extract(tmp_path):
    """Once the binary is on disk, resolve is a pure filesystem check -- no
    archive lookup, no autodownload check, no network -- since it is
    re-executed by this host for the whole session rather than pushed and
    discarded like frida-server."""
    payload = _make_archive(tmp_path, HostArch.linux_x86_64, "4.1", b"BINARY")
    (tmp_path / "scrcpy-linux-x86_64-v4.1.tar.gz").write_bytes(payload)
    repo = ScrcpyRepo(tmp_path)
    first = repo.resolve(version="4.1")
    # Remove the archive; a re-extraction attempt would now fail loudly.
    (tmp_path / "scrcpy-linux-x86_64-v4.1.tar.gz").unlink()
    second = repo.resolve(version="4.1")
    assert first == second
    assert second.is_file()


def test_extract_fetches_a_missing_asset_and_verifies_its_checksum(tmp_path, monkeypatch):
    """With autodownload on, a missing archive is fetched, its SHA-256 checked
    against the release's own published sums, and only then extracted."""
    payload = _make_archive(tmp_path / "build", HostArch.linux_x86_64, "4.1", b"FRESH")
    digest = hashlib.sha256(payload).hexdigest()
    archive_url = (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        "v4.1/scrcpy-linux-x86_64-v4.1.tar.gz"
    )
    sums_url = "https://github.com/Genymobile/scrcpy/releases/download/v4.1/SHA256SUMS.txt"

    class _FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _urlopen(url):
        assert url == sums_url
        return _FakeResponse(f"{digest}  scrcpy-linux-x86_64-v4.1.tar.gz\n".encode())

    monkeypatch.setattr(repo_mod.urllib.request, "urlopen", _urlopen)
    downloader = _FakeDownloader({archive_url: payload})
    settings = ScrcpySettings(autodownload_binary=True)
    repo = ScrcpyRepo(tmp_path, settings=settings, downloader=downloader)
    binary = repo.resolve(version="4.1")
    assert binary.read_bytes() == b"FRESH"
    assert downloader.calls == [archive_url]


def test_a_checksum_mismatch_removes_the_archive_and_refuses(tmp_path, monkeypatch):
    """A downloaded archive that does not match its published sum must never be
    extracted, and must not be left on disk for a later resolve to trust."""
    payload = _make_archive(tmp_path / "build", HostArch.linux_x86_64, "4.1", b"TAMPERED")
    archive_url = (
        "https://github.com/Genymobile/scrcpy/releases/download/"
        "v4.1/scrcpy-linux-x86_64-v4.1.tar.gz"
    )

    class _FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def _urlopen(url):
        return _FakeResponse(
            b"0" * 64 + b"  scrcpy-linux-x86_64-v4.1.tar.gz\n"
        )

    monkeypatch.setattr(repo_mod.urllib.request, "urlopen", _urlopen)
    downloader = _FakeDownloader({archive_url: payload})
    settings = ScrcpySettings(autodownload_binary=True)
    repo = ScrcpyRepo(tmp_path, settings=settings, downloader=downloader)
    with pytest.raises(ScrcpyChecksumError):
        repo.resolve(version="4.1")
    assert not (tmp_path / "scrcpy-linux-x86_64-v4.1.tar.gz").exists()


def test_scrcpy_repo_reads_the_dist_directory_under_gunkata_root(tmp_path, monkeypatch):
    """The factory every defaulting caller reaches through must resolve
    $GUNKATA_ROOT/dist, so an archive placed there is the one resolve() finds --
    mirroring frida.repo.server_repo()'s own test."""
    from gunkata.scrcpy.repo import scrcpy_repo

    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    dist = tmp_path / "dist"
    dist.mkdir()
    payload = _make_archive(tmp_path / "build", HostArch.linux_x86_64, "4.1", b"FROMDIST")
    (dist / "scrcpy-linux-x86_64-v4.1.tar.gz").write_bytes(payload)
    binary = scrcpy_repo().resolve(version="4.1")
    assert binary.read_bytes() == b"FROMDIST"
