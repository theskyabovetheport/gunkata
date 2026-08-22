import urllib.error

import pytest

from gunkata.common import download as download_mod
from gunkata.common.download import BinaryDownloader, BinaryDownloadError

_URL = "https://example.invalid/releases/download/16.1.4/frida-server-16.1.4-android-arm64.xz"


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False


def test_download_writes_the_response_body_to_dest(tmp_path, monkeypatch):
    """The exact bytes urlopen returns must land at dest, fetched from the URL
    the caller gave verbatim -- this class composes no URL of its own."""
    urls: list[str] = []

    def _urlopen(url):
        urls.append(url)
        return _FakeResponse(b"ELFELF")

    monkeypatch.setattr(download_mod.urllib.request, "urlopen", _urlopen)
    dest = tmp_path / "asset.xz"
    BinaryDownloader().download(_URL, dest)
    assert dest.read_bytes() == b"ELFELF"
    assert urls == [_URL]


def test_download_refuses_on_a_404_naming_the_url(tmp_path, monkeypatch):
    def _urlopen(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(download_mod.urllib.request, "urlopen", _urlopen)
    dest = tmp_path / "asset.xz"
    with pytest.raises(BinaryDownloadError) as exc:
        BinaryDownloader().download(_URL, dest)
    assert _URL in str(exc.value)
    assert not dest.exists()


class _FailingResponse(_FakeResponse):
    def read(self) -> bytes:
        raise OSError("connection reset")


def test_download_removes_the_partial_file_when_the_body_read_fails(
    tmp_path, monkeypatch
):
    """A failure after the temp file is created (mid-transfer) must not leave that
    ``.part`` file behind for a later run to mistake for a real download."""
    monkeypatch.setattr(
        download_mod.urllib.request, "urlopen", lambda url: _FailingResponse(b"")
    )
    dest = tmp_path / "asset.xz"
    with pytest.raises(BinaryDownloadError):
        BinaryDownloader().download(_URL, dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()
