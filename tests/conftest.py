import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fast_speech(monkeypatch):
    """No settle/start delays in tests (the queue itself is tested separately)."""
    from custom_components.remindo import manager

    monkeypatch.setattr(manager, "SPEAK_SETTLE", 0)
    monkeypatch.setattr(manager, "SPEAK_START_MAX", 0)
    yield
