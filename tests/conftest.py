"""Test setup: load custom_components/ from the repo root."""

import pytest

from fake_fitting import FakeBleakClient, FakeFitting


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def fitting(monkeypatch):
    """A simulated fitting; every establish_connection() returns a client bound to it."""
    f = FakeFitting()

    async def fake_connect(*args, **kwargs):
        return FakeBleakClient(f)

    monkeypatch.setattr("custom_components.hansa_ble.client.establish_connection", fake_connect)
    monkeypatch.setattr("custom_components.hansa_ble.client.VERIFY_READS", 1)
    monkeypatch.setattr("custom_components.hansa_ble.client._sleep", _no_sleep)
    return f


async def _no_sleep(_seconds):
    return None
