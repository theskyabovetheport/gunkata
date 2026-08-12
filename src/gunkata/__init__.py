"""gunkata: tools to improve security research workflows for Android devices."""

from .adb import Adb
from .addr import AddrLocator
from .device import Device
from .logcat import Level, Logcat, LogcatEntry
from .procmaps import AmbiguousProcessError, NoSuchProcessError, ProcMaps
from .ps import ProcessEntry, Ps
from .shell import Shell
from .stream import Stream
from .types import ShellResult


def device(serial: str | None = None):
    return Device(Adb(serial))


def shell(user: str | None = None, su_binary: str | None = None) -> Shell:
    return Device(Adb(), su_binary=su_binary).shell(user=user)


def sh(command: str) -> ShellResult:
    return shell().sh(command)


def logcat(tail: int | None = 1, follow: bool = True) -> Logcat:
    return Logcat(shell(), tail=tail, follow=follow)


def procmaps() -> ProcMaps:
    return ProcMaps(shell())


def ps() -> Ps:
    return Ps(shell())
