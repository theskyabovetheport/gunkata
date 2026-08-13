import importlib.util
import sys

import pytest

from gunkata.frida.dep import FridaUnavailableError, import_frida


def test_import_frida_refuses_with_install_hint_when_absent(monkeypatch):
    """Force the import to fail even when frida is installed, and check the
    refusal names the extra to install."""
    monkeypatch.setitem(sys.modules, "frida", None)
    with pytest.raises(FridaUnavailableError) as exc:
        import_frida()
    assert "gunkata[frida]" in str(exc.value)


@pytest.mark.skipif(
    importlib.util.find_spec("frida") is None, reason="frida extra not installed"
)
def test_import_frida_returns_the_module_when_installed():
    assert import_frida().__name__ == "frida"
