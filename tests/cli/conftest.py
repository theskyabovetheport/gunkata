import pytest

from gunkata.cli import completion


@pytest.fixture(autouse=True)
def _isolated_completion_cache(tmp_path, monkeypatch):
    """Point the completion cache at a per-test file so tests never share state
    with each other or with the real cache used by actual shell completion."""
    monkeypatch.setattr(
        completion, "_completion_cache_path", lambda: tmp_path / "cache.json"
    )
