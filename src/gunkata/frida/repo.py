"""Resolving one frida-server binary out of a local repo of release archives."""

import importlib.metadata
import lzma
import os
import re
import shutil
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from enum import Enum
from pathlib import Path

from ..common.paths import Paths
from ..shell import Shell

_VERSION = re.compile(r"\d+\.\d+\.\d+")


class UnsupportedAbiError(RuntimeError):
    """The device reports a CPU ABI frida ships no android-server build for."""


class VersionUnresolvedError(RuntimeError):
    """No version was given and no installed frida package to default from."""


class ServerAssetError(RuntimeError):
    """The frida-server archive this device needs is absent from the repo."""


class Arch(Enum):
    """A frida-server build target, in frida's own release-asset spelling.

    Design:
        Members are the exact ``{arch}`` token in
        ``frida-server-{version}-android-{arch}.xz`` -- the filename fragment
        itself, with no second spelling to fall out of step with it. Android's
        ABI strings are the input; ``from_abi`` is the only place they are read,
        and this enum is the single canonical output.
    """

    arm = "arm"
    arm64 = "arm64"
    x86 = "x86"
    x86_64 = "x86_64"

    @classmethod
    def from_abi(cls, abi: str) -> "Arch":
        """Map a device's ``ro.product.cpu.abi`` to its frida arch token.

        Args:
            abi: The device's primary ABI, e.g. ``arm64-v8a``.

        Returns:
            The frida arch whose release archives run on that ABI.

        Raises:
            UnsupportedAbiError: abi is not one frida ships an android build for;
                the message names the abi.
        """
        by_abi = {
            "arm64-v8a": cls.arm64,
            "armeabi-v7a": cls.arm,
            "armeabi": cls.arm,
            "x86_64": cls.x86_64,
            "x86": cls.x86,
        }
        try:
            return by_abi[abi]
        except KeyError:
            raise UnsupportedAbiError(
                f"device CPU ABI {abi!r} has no frida-server android build"
            ) from None


class ServerRepo:
    """A directory of frida-server release archives, resolved one at a time.

    Args:
        repo: Directory holding ``frida-server-{version}-android-{arch}.xz``
            archives exactly as downloaded from frida's GitHub releases.

    Design:
        Host-side and frida-free: it reads the device ABI over adb to pick an
        arch and the installed frida package's *metadata* (never importing the
        module) to default the version, then hands back a decompressed binary on
        the local filesystem for the device side to push. Not importing frida is
        what keeps provisioning working on a base ``gunkata`` install, as long as
        a version is supplied.
    """

    _ABI_PROP = "ro.product.cpu.abi"

    def __init__(self, repo: Path):
        self._repo = repo

    @contextmanager
    def extracted(
        self, shell: Shell, version: str | None = None
    ) -> Generator[Path, None, None]:
        """Yield a decompressed frida-server for this device; delete it after.

        Args:
            shell: Shell on the target device, read once for its ABI.
            version: frida version to resolve, or None to default to the
                installed frida package's version.

        Yields:
            Path to a freshly decompressed frida-server binary matching the
            device's ABI. The caller pushes it and marks it executable inside the
            ``with``; the temp file is removed on exit, even if the push raises.

        Raises:
            UnsupportedAbiError: The device ABI has no frida build.
            VersionUnresolvedError: version is None and frida is not installed.
            ServerAssetError: The matching archive is missing from the repo.

        Design:
            A context manager, like Stream, so a multi-hundred-megabyte temp
            binary cannot leak across runs; teardown is guaranteed even when the
            device push fails partway through the ``with``.
        """
        path = self._extract(shell, version)
        try:
            yield path
        finally:
            os.remove(path)

    def _extract(self, shell: Shell, version: str | None) -> Path:
        arch = Arch.from_abi(self._abi(shell))
        resolved = self._resolve_version(version)
        archive = self._archive(resolved, arch)
        return self._decompress(archive, resolved, arch)

    def _abi(self, shell: Shell) -> str:
        return shell.sh(f"getprop {self._ABI_PROP}").stdout

    def _resolve_version(self, version: str | None) -> str:
        """Fix the target version, defaulting to the installed frida's.

        Raises:
            VersionUnresolvedError: version is None and frida is not installed.
            ValueError: version is not a strict ``X.Y.Z`` release token; this
                also blocks path traversal in the archive lookup and injection
                once the version reaches the device start command.
        """
        if version is None:
            try:
                version = importlib.metadata.version("frida")
            except importlib.metadata.PackageNotFoundError:
                raise VersionUnresolvedError(
                    "frida is not installed, so no default server version is "
                    "known; pass version= (host client and server must match)"
                ) from None
        if not _VERSION.fullmatch(version):
            raise ValueError(
                f"frida version {version!r} is not a strict X.Y.Z release token"
            )
        return version

    def _archive(self, version: str, arch: Arch) -> Path:
        name = f"frida-server-{version}-android-{arch.value}.xz"
        archive = self._repo / name
        if not archive.is_file():
            raise ServerAssetError(f"no {name} in frida repo {self._repo}")
        return archive

    def _decompress(self, archive: Path, version: str, arch: Arch) -> Path:
        prefix = f"frida-server-{version}-android-{arch.value}-"
        fd, tmp = tempfile.mkstemp(prefix=prefix)
        try:
            with lzma.open(archive) as compressed, os.fdopen(fd, "wb") as binary:
                shutil.copyfileobj(compressed, binary)
        except BaseException:
            os.remove(tmp)
            raise
        return Path(tmp)


def server_repo() -> ServerRepo:
    """The frida-server repo configured for this process.

    Returns:
        A ``ServerRepo`` over ``Paths.from_env().dist`` (``$GUNKATA_ROOT/dist``).

    Design:
        The one place Paths meets the resolver, so callers reach the resolver
        through a factory rather than reading the environment at their own call
        site. There is no source Protocol today because there is exactly one
        source -- a local directory; a Protocol and registry for a single
        implementation is code written before its second caller. A second source
        introduces the Protocol and lets this factory resolve one by id.
    """
    return ServerRepo(Paths.from_env().dist)
