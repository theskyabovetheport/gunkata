"""Fetching a binary release asset over HTTP onto the local filesystem."""

import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class BinaryDownloadError(RuntimeError):
    """A release asset could not be fetched."""


class BinaryDownloader:
    """Fetches one release asset from a URL to a local path.

    Design:
        The one network-touching step in provisioning a binary, isolated in its
        own class so a repo's version/arch resolution stays testable without
        faking HTTP -- a test substitutes this class instead. It takes a URL
        rather than composing one, because each repo's release host spells its
        download paths differently; the template belongs with the repo that
        knows its own asset naming.
    """

    def download(self, url: str, dest: Path) -> None:
        """Fetch url into dest.

        Args:
            url: The release asset's full download URL.
            dest: Where the downloaded bytes land.

        Raises:
            BinaryDownloadError: The request failed -- a network error, or any
                non-2xx response, including a 404 for a version/arch the
                project never released.

        Design:
            Written to a same-directory ``.part`` file and renamed into dest
            only once the download completes, so a caller never observes a
            truncated archive at dest -- a failure partway through leaves
            only the ``.part`` file, which is removed before raising.
        """
        tmp = dest.with_name(dest.name + ".part")
        try:
            with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:
                out.write(response.read())
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise BinaryDownloadError(f"failed to download {url}: {exc}") from exc
        tmp.rename(dest)
        logger.info("release asset downloaded", extra={"url": url, "dest": str(dest)})
