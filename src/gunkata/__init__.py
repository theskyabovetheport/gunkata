"""gunkata: tools to improve security research workflows for Android devices."""

from .adb import Adb
from .addr import AddrLocator
from .device import Device
from .frida import (
    Arch,
    FridaClient,
    FridaServer,
    Injection,
    ServerRepo,
    inject,
    server_repo,
)
from .logcat import Level, Logcat, LogcatEntry
from .memory import Memory, UnmappedRangeError
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


def memory(pid: int) -> Memory:
    device_shell = shell()
    return Memory(device_shell, pid, ProcMaps(device_shell))


def frida_server(
    serial: str | None = None,
    version: str | None = None,
    su_binary: str | None = None,
) -> FridaServer:
    return Device(Adb(serial), su_binary=su_binary).frida_server(
        server_repo(), version=version
    )


def frida(serial: str | None = None, timeout: float = 10.0) -> FridaClient:
    return Device(Adb(serial)).frida(timeout=timeout)
