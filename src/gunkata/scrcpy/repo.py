"""Resolving one scrcpy binary out of a local repo of release archives."""

import hashlib
import platform
import re
import tarfile
import urllib.request
from enum import Enum
from pathlib import Path

from ..common.download import BinaryDownloader
from ..common.paths import Paths
from .settings import ScrcpySettings

_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")
_RELEASES = "https://github.com/Genymobile/scrcpy/releases/download"


class UnsupportedHostError(RuntimeError):
    """This host's OS/CPU has no scrcpy release build; the frame needs Linux X11."""


class ScrcpyAssetError(RuntimeError):
    """The scrcpy release archive this host needs is absent from the repo."""


class ScrcpyChecksumError(RuntimeError):
    """A downloaded scrcpy archive did not match its published SHA-256 sum."""


class HostArch(Enum):
    """A scrcpy release build target, in scrcpy's own release-asset spelling.

    Design:
        Members are the exact ``{arch}`` token in
        ``scrcpy-{arch}-v{version}.tar.gz`` -- the filename fragment itself,
        with no second spelling to fall out of step with it. Only the target
        this feature actually runs on has a member: Xephyr is X11-only, so
        the whole command is Linux-only regardless of what else scrcpy
        publishes, and a macOS/Windows member would be a value with no caller.
    """

    linux_x86_64 = "linux-x86_64"

    @classmethod
    def from_platform(cls) -> "HostArch":
        """Map this host's OS/CPU to its scrcpy release arch token.

        Raises:
            UnsupportedHostError: This host is not Linux/x86_64 -- the message
                names what platform.system()/machine() actually reported.
        """
        system = platform.system()
        machine = platform.machine()
        if system == "Linux" and machine in ("x86_64", "AMD64"):
            return cls.linux_x86_64
        raise UnsupportedHostError(
            f"no scrcpy release build for {system}/{machine}; "
            "gunkata scrcpy needs a Linux x86_64 host to run Xephyr"
        )


class ScrcpyRepo:
    """A directory of scrcpy release archives, resolved one at a time.

    Args:
        repo: Directory holding ``scrcpy-{arch}-v{version}.tar.gz`` archives
            exactly as downloaded from scrcpy's GitHub releases, and their
            extracted directories.
        settings: Version to resolve and whether a missing archive may be
            fetched automatically, resolved from the environment. None builds
            a fresh ScrcpySettings.
        downloader: Fetches a missing archive when settings allows it. None
            builds a fresh BinaryDownloader.

    Design:
        Structural twin of frida.repo.ServerRepo: host-side, one archive
        format, one factory. It differs in two ways a host binary calls for
        that a device binary does not. First, ``resolve`` returns a path to
        keep rather than a temp file to push-and-delete -- this binary is
        re-executed by this host for the life of the session, not shipped
        elsewhere, so extraction is idempotent and a second resolve of the
        same version/arch is a no-op. Second, a release archive fetched over
        the network and then executed on this host gets its SHA-256 verified
        against the release's own published sums before extraction; frida's
        server binary is pushed to a device and never executed by this host
        at all, so it has no matching step.
    """

    def __init__(
        self,
        repo: Path,
        settings: ScrcpySettings | None = None,
        downloader: BinaryDownloader | None = None,
    ):
        self._repo = repo
        self._settings = settings if settings is not None else ScrcpySettings()
        self._downloader = downloader if downloader is not None else BinaryDownloader()

    def resolve(self, version: str | None = None) -> Path:
        """Return this host's scrcpy executable, extracting it if needed.

        Args:
            version: scrcpy version to resolve, or None to default to
                settings.version.

        Returns:
            Path to the extracted ``scrcpy`` executable. Its ``scrcpy-server``
            sibling lives in the same directory, exactly as the release
            archive laid them out.

        Raises:
            UnsupportedHostError: This host has no scrcpy release build.
            ValueError: version is not a strict ``X.Y`` or ``X.Y.Z`` release
                token.
            ScrcpyAssetError: The matching archive is missing from the repo
                and settings.autodownload_binary is not set.
            BinaryDownloadError: autodownload_binary is set and the download
                failed.
            ScrcpyChecksumError: autodownload_binary is set and the freshly
                downloaded archive does not match its published SHA-256 sum.
        """
        arch = HostArch.from_platform()
        resolved = self._resolve_version(version)
        extracted = self._extracted_dir(resolved, arch)
        binary = extracted / "scrcpy"
        if binary.is_file():
            return binary
        archive = self._archive(resolved, arch)
        self._repo.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(path=self._repo, filter="data")
        return binary

    def _resolve_version(self, version: str | None) -> str:
        if version is None:
            version = self._settings.version
        if not _VERSION.fullmatch(version):
            raise ValueError(
                f"scrcpy version {version!r} is not a strict X.Y or X.Y.Z release token"
            )
        return version

    def _asset_name(self, version: str, arch: HostArch) -> str:
        return f"scrcpy-{arch.value}-v{version}.tar.gz"

    def _extracted_dir(self, version: str, arch: HostArch) -> Path:
        # The archive's own top-level directory is named identically -- tar
        # extraction lands here without a second name to keep in step with it.
        return self._repo / f"scrcpy-{arch.value}-v{version}"

    def _archive(self, version: str, arch: HostArch) -> Path:
        name = self._asset_name(version, arch)
        archive = self._repo / name
        if archive.is_file():
            return archive
        if not self._settings.autodownload_binary:
            raise ScrcpyAssetError(
                f"no {name} in scrcpy repo {self._repo}; place it there yourself, "
                "or set GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY=1 to fetch it from "
                "scrcpy's GitHub releases automatically"
            )
        self._repo.mkdir(parents=True, exist_ok=True)
        url = f"{_RELEASES}/v{version}/{name}"
        self._downloader.download(url, archive)
        try:
            self._verify_checksum(archive, version, name)
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
        return archive

    def _verify_checksum(self, archive: Path, version: str, name: str) -> None:
        """Check archive's SHA-256 against scrcpy's published SHA256SUMS.txt.

        Raises:
            ScrcpyChecksumError: The sums file has no line for name, or
                archive's own hash does not match the line it has.

        Design:
            SHA256SUMS.txt is fetched straight into memory rather than
            through BinaryDownloader: it is read once and never kept, unlike
            an archive this class caches on disk, so the download-and-rename
            machinery that protects a cached asset would only add a temp file
            with nothing to protect.
        """
        sums_url = f"{_RELEASES}/v{version}/SHA256SUMS.txt"
        with urllib.request.urlopen(sums_url) as response:
            sums_text = response.read().decode("utf-8", errors="replace")
        expected = None
        for line in sums_text.splitlines():
            digest, _, filename = line.strip().partition("  ")
            if filename == name:
                expected = digest
                break
        if expected is None:
            raise ScrcpyChecksumError(f"{name} has no entry in {sums_url}")
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise ScrcpyChecksumError(
                f"{name} sha256 {actual} does not match published {expected}"
            )


def scrcpy_repo() -> ScrcpyRepo:
    """The scrcpy repo configured for this process.

    Returns:
        A ``ScrcpyRepo`` over ``Paths.from_env().dist`` (``$GUNKATA_ROOT/dist``),
        the same shared download cache frida's server_repo() uses.

    Design:
        The one place Paths meets the resolver, so callers reach it through a
        factory rather than reading the environment at their own call site --
        the same rationale as frida.repo.server_repo.
    """
    return ScrcpyRepo(Paths.from_env().dist)
