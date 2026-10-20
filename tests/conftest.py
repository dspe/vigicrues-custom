"""Tests use real Home Assistant classes with isolated network/storage boundaries."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.vigicrues.coordinator import VigicruesDataUpdateCoordinator


@pytest.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    yield instance
    await instance.async_stop(force=True)


@pytest.fixture
def entry():
    result = MagicMock(spec=ConfigEntry)
    result.data = {
        "station_id": "F700000103",
        "station_name": "Paris",
        "troncon_id": "IF7",
    }
    result.options = {}
    result.entry_id = "test_station"
    result.state = ConfigEntryState.SETUP_IN_PROGRESS
    result.pref_disable_polling = False
    result.async_create_background_task.side_effect = lambda hass, coro, **kwargs: (
        hass.async_create_task(coro)
    )
    return result


@pytest.fixture
async def coordinator(hass, entry):
    with patch("custom_components.vigicrues.coordinator.async_get_clientsession"):
        result = VigicruesDataUpdateCoordinator(hass, entry)
    result._store = MagicMock()
    result._store.async_load = AsyncMock(return_value=None)
    result._store.async_save = AsyncMock()
    result._store.async_remove = AsyncMock()
    result.api = MagicMock()
    result.api.get_station_details = AsyncMock(return_value=None)
    result.api.get_station_data = AsyncMock()
    yield result
    await result.async_shutdown()


@pytest.fixture
async def http_server():
    """Serve real aiohttp responses without reaching external services."""
    from aiohttp import web

    runners = []

    async def start(handler):
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    yield start
    for runner in runners:
        await runner.cleanup()
