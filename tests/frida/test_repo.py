import importlib.metadata
import lzma
from pathlib import Path

import pytest

from gunkata.frida.repo import (
    Arch,
    ServerAssetError,
    ServerRepo,
    UnsupportedAbiError,
    VersionUnresolvedError,
)
from gunkata.types import ShellResult


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
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "17.17.0")
    with pytest.raises(ServerAssetError) as exc:
        with ServerRepo(tmp_path).extracted(_FakeShell("x86_64")):
            pass
    message = str(exc.value)
    assert "frida-server-17.17.0-android-x86_64.xz" in message
    assert str(tmp_path) in message


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


@pytest.mark.parametrize("bad", ["16.5", "16.5.9; rm -rf /", "latest", "../etc"])
def test_version_rejects_non_release_token(tmp_path, bad):
    """A version string that is not a strict X.Y.Z is refused before it can build
    a filename or reach a device command."""
    with pytest.raises(ValueError):
        with ServerRepo(tmp_path).extracted(_FakeShell("x86_64"), version=bad):
            pass
