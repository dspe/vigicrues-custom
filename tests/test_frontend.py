"""The card asset is served from the integration, without a CDN dependency."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.vigicrues import async_setup


async def test_register_card_once_during_component_setup(hass):
    hass.http = SimpleNamespace(async_register_static_paths=AsyncMock())
    assert await async_setup(hass, {})
    paths = hass.http.async_register_static_paths.call_args.args[0]
    assert len(paths) == 1
    assert paths[0].url_path == "/vigicrues/vigicrues-card.js"
    assert await hass.async_add_executor_job(Path(paths[0].path).is_file)
