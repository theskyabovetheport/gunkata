import types

import pytest

from gunkata.frida import injection as injection_mod
from gunkata.frida.injection import Injection, inject


class _FakeError(Exception):
    pass


class _FakeInvalidOp(_FakeError):
    pass


def _fake_frida():
    return types.SimpleNamespace(Error=_FakeError, InvalidOperationError=_FakeInvalidOp)


class _Script:
    def __init__(self):
        self.events: list[tuple[str, object]] = []
        self.log_handler = None
        self.source = None
        self.loaded = False
        self.unloaded = False

    def set_log_handler(self, handler):
        self.log_handler = handler

    def on(self, name, callback):
        self.events.append((name, callback))

    def load(self):
        self.loaded = True

    def unload(self):
        self.unloaded = True


class _Session:
    def __init__(self, script):
        self._script = script
        self.detached = False

    def create_script(self, source):
        self._script.source = source
        return self._script

    def detach(self):
        self.detached = True


class _FakeFridaDevice:
    def __init__(self, script):
        self._session = _Session(script)
        self.spawned = None
        self.attached = None
        self.resumed = None
        self.killed = None

    def spawn(self, target):
        self.spawned = target
        return 4321

    def attach(self, target):
        self.attached = target
        return self._session

    def resume(self, pid):
        self.resumed = pid

    def kill(self, pid):
        self.killed = pid


@pytest.fixture(autouse=True)
def _fake_import(monkeypatch):
    """inject() pulls frida through import_frida; give it a fake so no real frida
    is needed and the fake's exception types are used."""
    monkeypatch.setattr(injection_mod, "import_frida", _fake_frida)


def test_inject_attaches_routes_console_then_loads():
    script = _Script()
    device = _FakeFridaDevice(script)
    handle = inject(device, "com.app", "//js")
    assert device.attached == "com.app"
    assert script.log_handler is not None
    assert script.loaded
    assert isinstance(handle, Injection)


def test_inject_spawn_attaches_by_the_spawned_pid():
    script = _Script()
    device = _FakeFridaDevice(script)
    inject(device, "com.app", "//js", spawn=True)
    assert device.spawned == "com.app"
    assert device.attached == 4321


def test_close_unloads_detaches_and_kills_a_suspended_spawn():
    device = _FakeFridaDevice(_Script())
    handle = inject(device, "com.app", "//js", spawn=True)
    handle.close()
    assert device._session.detached
    assert device.killed == 4321


def test_close_is_idempotent():
    device = _FakeFridaDevice(_Script())
    handle = inject(device, "com.app", "//js", spawn=True)
    handle.close()
    handle.close()
    assert device.killed == 4321


def test_a_resumed_spawn_is_not_killed_on_close():
    device = _FakeFridaDevice(_Script())
    handle = inject(device, "com.app", "//js", spawn=True)
    handle.resume()
    assert device.resumed == 4321
    handle.close()
    assert device.killed is None


def test_resume_refuses_when_attached_not_spawned():
    device = _FakeFridaDevice(_Script())
    handle = inject(device, "com.app", "//js")
    with pytest.raises(_FakeInvalidOp):
        handle.resume()


def test_on_message_callback_is_registered():
    script = _Script()
    device = _FakeFridaDevice(script)

    def callback(message, data):
        pass

    inject(device, "com.app", "//js", on_message=callback)
    assert ("message", callback) in script.events
