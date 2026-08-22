from gunkata.scrcpy.settings import ScrcpySettings

_ENV_BY_FIELD = {
    "version": "GUNKATA_SCRCPY_VERSION",
    "autodownload_binary": "GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY",
    "xephyr_binary": "GUNKATA_SCRCPY_XEPHYR_BINARY",
    "matchbox_binary": "GUNKATA_SCRCPY_MATCHBOX_BINARY",
    "frame_ready_timeout_seconds": "GUNKATA_SCRCPY_FRAME_READY_TIMEOUT_SECONDS",
    "boot_timeout_seconds": "GUNKATA_SCRCPY_BOOT_TIMEOUT_SECONDS",
    "poll_interval_seconds": "GUNKATA_SCRCPY_POLL_INTERVAL_SECONDS",
    "stop_grace_seconds": "GUNKATA_SCRCPY_STOP_GRACE_SECONDS",
    "min_uptime_seconds": "GUNKATA_SCRCPY_MIN_UPTIME_SECONDS",
    "launch_failure_limit": "GUNKATA_SCRCPY_LAUNCH_FAILURE_LIMIT",
}


def _clear_env(monkeypatch):
    for env_var in _ENV_BY_FIELD.values():
        monkeypatch.delenv(env_var, raising=False)


def test_defaults_when_env_unset(monkeypatch):
    """With no GUNKATA_SCRCPY_* vars set, every field takes its documented default."""
    _clear_env(monkeypatch)
    settings = ScrcpySettings()
    assert settings.version == "4.1"
    assert settings.autodownload_binary is False
    assert settings.xephyr_binary == "Xephyr"
    assert settings.matchbox_binary == "matchbox-window-manager"
    assert settings.frame_ready_timeout_seconds == 10.0
    assert settings.boot_timeout_seconds == 180.0
    assert settings.poll_interval_seconds == 0.5
    assert settings.stop_grace_seconds == 3.0
    assert settings.min_uptime_seconds == 2.0
    assert settings.launch_failure_limit == 3


def test_each_field_honors_its_env_var(monkeypatch):
    """Every field is independently overridable via its own GUNKATA_SCRCPY_* var."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("GUNKATA_SCRCPY_VERSION", "4.0")
    monkeypatch.setenv("GUNKATA_SCRCPY_AUTODOWNLOAD_BINARY", "1")
    monkeypatch.setenv("GUNKATA_SCRCPY_XEPHYR_BINARY", "/usr/bin/Xephyr")
    monkeypatch.setenv("GUNKATA_SCRCPY_MATCHBOX_BINARY", "/usr/bin/mbwm")
    monkeypatch.setenv("GUNKATA_SCRCPY_FRAME_WIDTH", "800")
    monkeypatch.setenv("GUNKATA_SCRCPY_FRAME_HEIGHT", "600")
    monkeypatch.setenv("GUNKATA_SCRCPY_FRAME_READY_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("GUNKATA_SCRCPY_BOOT_TIMEOUT_SECONDS", "60.0")
    monkeypatch.setenv("GUNKATA_SCRCPY_POLL_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("GUNKATA_SCRCPY_STOP_GRACE_SECONDS", "1.0")
    monkeypatch.setenv("GUNKATA_SCRCPY_MIN_UPTIME_SECONDS", "5.0")
    monkeypatch.setenv("GUNKATA_SCRCPY_LAUNCH_FAILURE_LIMIT", "7")
    settings = ScrcpySettings()
    assert settings.version == "4.0"
    assert settings.autodownload_binary is True
    assert settings.xephyr_binary == "/usr/bin/Xephyr"
    assert settings.matchbox_binary == "/usr/bin/mbwm"
    assert settings.frame_ready_timeout_seconds == 1.5
    assert settings.boot_timeout_seconds == 60.0
    assert settings.poll_interval_seconds == 0.05
    assert settings.stop_grace_seconds == 1.0
    assert settings.min_uptime_seconds == 5.0
    assert settings.launch_failure_limit == 7
