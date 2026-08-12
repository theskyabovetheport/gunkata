from pathlib import Path

from gunkata.common.paths import Paths


def test_root_defaults_to_home_dot_gunkata(monkeypatch):
    """GUNKATA_ROOT unset must default to ~/.gunkata, not some other convention."""
    monkeypatch.delenv("GUNKATA_ROOT", raising=False)
    assert Paths.from_env().root == Path.home() / ".gunkata"


def test_root_honors_gunkata_root_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    assert Paths.from_env().root == tmp_path


def test_derived_paths_nest_under_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GUNKATA_ROOT", str(tmp_path))
    paths = Paths.from_env()
    assert paths.devices_dir == tmp_path / "devices"
    assert paths.list_config_path == tmp_path / "devices" / "list-config.yaml"
    info_dir = tmp_path / "devices" / "info"
    assert paths.device_name_path("emulator-5554") == info_dir / "emulator-5554-name"
    assert paths.device_tags_path("emulator-5554") == info_dir / "emulator-5554-tags"
    assert paths.device_note_path("emulator-5554") == info_dir / "emulator-5554-note"
