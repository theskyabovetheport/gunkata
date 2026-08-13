import importlib.util
import types

import pytest

from gunkata.frida import client as client_mod
from gunkata.frida.client import FridaClient, FridaNotReadyError, frida_client


class _FakeError(Exception):
    pass


class _Device:
    """A fake frida device whose server answers only after ``fails`` refusals."""

    def __init__(self, fails: int):
        self._fails = fails
        self.queries = 0

    def query_system_parameters(self):
        self.queries += 1
        if self.queries <= self._fails:
            raise _FakeError("not ready")
        return {"os": {"version": "14"}}


def _fake_frida(device):
    manager = types.SimpleNamespace(get_device=lambda serial, timeout: device)
    return types.SimpleNamespace(Error=_FakeError, get_device_manager=lambda: manager)


def test_frida_client_retries_until_the_server_answers(monkeypatch):
    device = _Device(fails=2)
    monkeypatch.setattr(client_mod, "import_frida", lambda: _fake_frida(device))
    client = frida_client("emulator-5554", timeout=5.0, poll=0.0)
    assert isinstance(client, FridaClient)
    assert device.queries == 3


def test_frida_client_times_out_naming_the_serial(monkeypatch):
    device = _Device(fails=10**9)
    monkeypatch.setattr(client_mod, "import_frida", lambda: _fake_frida(device))
    with pytest.raises(FridaNotReadyError) as exc:
        frida_client("emulator-5554", timeout=0.0, poll=0.0)
    assert "emulator-5554" in str(exc.value)


@pytest.mark.emulator
@pytest.mark.skipif(
    importlib.util.find_spec("frida") is None, reason="frida extra not installed"
)
def test_frida_client_against_real_device(device):
    """With frida-server running, a client binds to the serial and the server
    answers a system-parameters query."""
    import gunkata

    server = device.frida_server(gunkata.server_repo())
    server.start()
    try:
        client = device.frida()
        assert "os" in client.device.query_system_parameters()
    finally:
        server.stop()
