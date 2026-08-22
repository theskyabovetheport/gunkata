from gunkata.frida.settings import FridaSettings

_ENV_BY_FIELD = {
    "device_path": "GUNKATA_FRIDA_DEVICE_PATH",
    "port": "GUNKATA_FRIDA_PORT",
    "start_timeout_seconds": "GUNKATA_FRIDA_START_TIMEOUT_SECONDS",
    "stop_grace_seconds": "GUNKATA_FRIDA_STOP_GRACE_SECONDS",
    "poll_interval_seconds": "GUNKATA_FRIDA_POLL_INTERVAL_SECONDS",
    "connect_timeout_seconds": "GUNKATA_FRIDA_CONNECT_TIMEOUT_SECONDS",
    "connect_poll_seconds": "GUNKATA_FRIDA_CONNECT_POLL_SECONDS",
    "autodownload_server_binary": "GUNKATA_FRIDA_AUTODOWNLOAD_SERVER_BINARY",
    "assume_running": "GUNKATA_FRIDA_ASSUME_RUNNING",
}


def _clear_env(monkeypatch):
    for env_var in _ENV_BY_FIELD.values():
        monkeypatch.delenv(env_var, raising=False)


def test_defaults_when_env_unset(monkeypatch):
    """With no GUNKATA_FRIDA_* vars set, every field takes its documented default."""
    _clear_env(monkeypatch)
    settings = FridaSettings()
    assert settings.device_path == "/data/local/tmp/frida-server"
    assert settings.port == 27042
    assert settings.start_timeout_seconds == 10.0
    assert settings.stop_grace_seconds == 3.0
    assert settings.poll_interval_seconds == 0.1
    assert settings.connect_timeout_seconds == 10.0
    assert settings.connect_poll_seconds == 0.25
    assert settings.autodownload_server_binary is False
    assert settings.assume_running is False


def test_each_field_honors_its_env_var(monkeypatch):
    """Every field is independently overridable via its own GUNKATA_FRIDA_* var."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("GUNKATA_FRIDA_DEVICE_PATH", "/data/local/tmp/fs")
    monkeypatch.setenv("GUNKATA_FRIDA_PORT", "9999")
    monkeypatch.setenv("GUNKATA_FRIDA_START_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("GUNKATA_FRIDA_STOP_GRACE_SECONDS", "2.5")
    monkeypatch.setenv("GUNKATA_FRIDA_POLL_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("GUNKATA_FRIDA_CONNECT_TIMEOUT_SECONDS", "20.0")
    monkeypatch.setenv("GUNKATA_FRIDA_CONNECT_POLL_SECONDS", "0.5")
    monkeypatch.setenv("GUNKATA_FRIDA_AUTODOWNLOAD_SERVER_BINARY", "1")
    monkeypatch.setenv("GUNKATA_FRIDA_ASSUME_RUNNING", "1")
    settings = FridaSettings()
    assert settings.device_path == "/data/local/tmp/fs"
    assert settings.port == 9999
    assert settings.start_timeout_seconds == 1.5
    assert settings.stop_grace_seconds == 2.5
    assert settings.poll_interval_seconds == 0.05
    assert settings.connect_timeout_seconds == 20.0
    assert settings.connect_poll_seconds == 0.5
    assert settings.autodownload_server_binary is True
    assert settings.assume_running is True
