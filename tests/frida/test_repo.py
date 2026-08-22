import importlib.metadata
import lzma
from pathlib import Path

import pytest

from gunkata.common.download import BinaryDownloadError
from gunkata.frida.repo import (
    Arch,
    ServerAssetError,
    ServerRepo,
    UnsupportedAbiError,
    VersionUnresolvedError,
    server_repo,
)
from gunkata.frida.settings import FridaSettings
from gunkata.shell import ShellResult


class _FakeShell:
    """A Shell double that answers only ``getprop`` with a fixed ABI."""

    def __init__(self, abi: str):
        self._abi = abi

    def sh(self, command: str, strip: bool = True) -> ShellResult:
        return ShellResult(command=command, stdout=self._abi, stderr="", rc=0)


def _write_archive(repo: Path, version: str, arch: str, payload: bytes) -> None:
    name = f"frida-server-{version}-android-{arch}.xz"
    (repo / name).write_bytes(lzma.compress(payload))


@pytest.mark.parametrize(
    "abi,arch",
    [
        ("arm64-v8a", Arch.arm64),
        ("armeabi-v7a", Arch.arm),
        ("armeabi", Arch.arm),
        ("x86_64", Arch.x86_64),
        ("x86", Arch.x86),
    ],
)
def test_from_abi_maps_every_supported_abi(abi, arch):
    assert Arch.from_abi(abi) == arch


def test_from_abi_refuses_unknown_abi_naming_it():
    with pytest.raises(UnsupportedAbiError) as exc:
        Arch.from_abi("mips")
    assert "mips" in str(exc.value)


def test_extract_picks_matching_asset_and_decompresses(tmp_path, monkeypatch):
    """The chosen archive must match the device ABI and default version, and its
    decompressed bytes must reach the caller unchanged."""
    _write_archive(tmp_path, "17.17.0", "x86_64", b"FAKEELF")
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "17.17.0")
    with ServerRepo(tmp_path).extracted(_FakeShell("x86_64")) as local:
        assert local.read_bytes() == b"FAKEELF"
        assert local.name.startswith("frida-server-17.17.0-android-x86_64-")


def test_extracted_deletes_the_temp_file_on_exit(tmp_path, monkeypatch):
    _write_archive(tmp_path, "17.17.0", "x86_64", b"FAKEELF")
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "17.17.0")
    with ServerRepo(tmp_path).extracted(_FakeShell("x86_64")) as local:
        captured = local
        assert captured.exists()
    assert not captured.exists()


def test_extract_refuses_missing_asset_naming_file_and_repo(tmp_path, monkeypatch):
    """With autodownload off (its default), a missing archive is refused with a
    message naming the file, the repo, and the env var that would fetch it."""
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "17.17.0")
    settings = FridaSettings(autodownload_server_binary=False)
    with pytest.raises(ServerAssetError) as exc:
        with ServerRepo(tmp_path, settings=settings).extracted(_FakeShell("x86_64")):
            pass
    message = str(exc.value)
    assert "frida-server-17.17.0-android-x86_64.xz" in message
    assert str(tmp_path) in message
    assert "GUNKATA_FRIDA_AUTODOWNLOAD_SERVER_BINARY" in message


class _FakeDownloader:
    """Writes a canned payload to dest instead of touching the network."""

    def __init__(self, payload: bytes):
        self._payload = payload
        self.calls: list[str] = []

    def download(self, url, dest):
        self.calls.append(url)
        dest.write_bytes(lzma.compress(self._payload))


class _FailingDownloader:
    def download(self, url, dest):
        raise BinaryDownloadError(f"failed to download {url}")


def test_extract_fetches_a_missing_asset_when_autodownload_is_set(
    tmp_path, monkeypatch
):
    """With autodownload on, a missing archive is fetched through the injected
    downloader -- for exactly the version/arch the device needs -- and the
    fetched bytes decompress the same as one that was already on disk."""
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "17.17.0")
    downloader = _FakeDownloader(b"FRESH")
    settings = FridaSettings(autodownload_server_binary=True)
    repo = ServerRepo(tmp_path, settings=settings, downloader=downloader)
    with repo.extracted(_FakeShell("x86_64")) as local:
        assert local.read_bytes() == b"FRESH"
    assert downloader.calls == [
        "https://github.com/frida/frida/releases/download/17.17.0/"
        "frida-server-17.17.0-android-x86_64.xz"
    ]


def test_extract_propagates_a_download_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "17.17.0")
    settings = FridaSettings(autodownload_server_binary=True)
    repo = ServerRepo(tmp_path, settings=settings, downloader=_FailingDownloader())
    with pytest.raises(BinaryDownloadError):
        with repo.extracted(_FakeShell("x86_64")):
            pass


def test_version_defaults_to_the_installed_frida(tmp_path, monkeypatch):
    _write_archive(tmp_path, "16.5.9", "arm64", b"X")
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "16.5.9")
    with ServerRepo(tmp_path).extracted(_FakeShell("arm64-v8a")) as local:
        assert local.read_bytes() == b"X"


def test_version_refused_when_frida_absent_and_unset(tmp_path, monkeypatch):
    def _absent(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _absent)
    with pytest.raises(VersionUnresolvedError):
        with ServerRepo(tmp_path).extracted(_FakeShell("x86_64")):
            pass


def test_server_repo_reads_the_dist_directory_under_gunkata_root(tmp_path, monkeypatch):
    """The factory every defaulting caller reaches through must resolve
    $GUNKATA_ROOT/dist, so an archive placed there is the one provisioning finds."""
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    dist = tmp_path / "dist"
    dist.mkdir()
    _write_archive(dist, "17.17.0", "x86_64", b"FROMDIST")
    with server_repo().extracted(_FakeShell("x86_64"), version="17.17.0") as local:
        assert local.read_bytes() == b"FROMDIST"


@pytest.mark.parametrize("bad", ["16.5", "16.5.9; rm -rf /", "latest", "../etc"])
def test_version_rejects_non_release_token(tmp_path, bad):
    """A version string that is not a strict X.Y.Z is refused before it can build
    a filename or reach a device command."""
    with pytest.raises(ValueError):
        with ServerRepo(tmp_path).extracted(_FakeShell("x86_64"), version=bad):
            pass
