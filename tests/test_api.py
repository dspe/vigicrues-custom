"""Exercise payload handling, failures, fallback, units and independent resources."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import web

from custom_components.vigicrues.api import (
    Observation,
    Station,
    VigicruesAPI,
    VigicruesAPIError,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def obs(value=1, *, minutes=0, source="vigicrues"):
    return Observation(
        value, datetime.now(UTC) - timedelta(minutes=minutes), "m", source
    )


@pytest.fixture
async def api():
    async with aiohttp.ClientSession() as session:
        yield VigicruesAPI(session)


@pytest.mark.parametrize("failure", [503, 429, 403, "html", "json", "timeout", "dns"])
async def test_request_normalizes_expected_failures(api, failure, http_server):
    if failure in ("timeout", "dns"):
        exception = (
            TimeoutError()
            if failure == "timeout"
            else aiohttp.ClientConnectionError("DNS failure")
        )
        with patch.object(api._session, "get", side_effect=exception):
            with pytest.raises(VigicruesAPIError):
                await api._request("https://example.test/api")
        return

    async def handler(request):
        if isinstance(failure, int):
            return web.Response(status=failure)
        return web.Response(
            text="<html>maintenance</html>",
            content_type="text/html" if failure == "html" else "application/json",
        )

    url = await http_server(handler)
    with pytest.raises(VigicruesAPIError):
        await api._request(url)


async def test_reference_feeds_include_station_types_7_and_8(api):
    api._request = AsyncMock(return_value=fixture("stations"))
    stations = await api.get_stations(territory_id="7")
    assert {s.id for s in stations} >= {"F330000102", "H240201001"}
    assert next(s for s in stations if s.id == "F330000102").troncon_id == "IF10"
    assert all(s.territory_id == "7" for s in stations)
    api._request.return_value = fixture("station")
    station = await api.get_station_details("F700000103")
    assert station.cours_eau == "Seine"
    assert (
        station.troncon_id is None
    )  # upstream placeholder must not override configuration
    assert station.latitude is None  # Lambert coordinates are not WGS84
    api._request.return_value = fixture("territories")
    assert len(await api.get_territories()) == 20


async def test_forecast_schema_and_zero_bounds(api):
    data = fixture("forecast")
    now = datetime.now(UTC)
    items = data["Simul"]["Prevs"]
    for i, item in enumerate(items):
        item["DtPrev"] = (now + timedelta(hours=i + 1)).isoformat()
    items[0]["ResMinPrev"] = 0
    items[0]["ResMaxPrev"] = 0
    api._request = AsyncMock(return_value=data)
    forecasts = await api.get_previsions("M800001010")
    assert forecasts[0].value == items[0]["ResMoyPrev"]
    assert forecasts[0].min_value == forecasts[0].max_value == 0
    api._request.return_value = {"Simul": {"Prevs": []}, "code": 204}
    assert await api.get_previsions("M800001010") == []


async def test_real_vigilance_fields(api):
    api._request = AsyncMock(return_value=fixture("vigilance"))
    assert (await api.get_vigilance_levels())["CO1"] == "Jaune"
    api._request.return_value = {"features": []}
    with pytest.raises(VigicruesAPIError):
        await api.get_vigilance_levels()


@pytest.mark.parametrize("grandeur,value,expected", [("H", 900, 0.9), ("Q", 12000, 12)])
async def test_http_fallback_accepts_206_and_converts_units(
    api, grandeur, value, expected, http_server, monkeypatch
):
    from custom_components.vigicrues import api as api_module

    calls = []

    async def handler(request):
        calls.append(request.path)
        if request.path == "/primary":
            assert request.query["GrdSerie"] == grandeur
            return web.Response(status=503)
        assert request.query["code_entite"] == "F700000103"
        assert request.query["sort"] == "desc"
        assert request.query["grandeur_hydro"] == grandeur
        return web.json_response(
            {
                "data": [
                    {
                        "code_station": "F700000103",
                        "grandeur_hydro": grandeur,
                        "date_obs": datetime.now(UTC).isoformat(),
                        "resultat_obs": value,
                    },
                ]
            },
            status=206,
        )

    url = await http_server(handler)
    monkeypatch.setattr(api_module, "ENDPOINT_OBSERVATIONS", url + "/primary")
    monkeypatch.setattr(api_module, "ENDPOINT_HUBEAU_OBSERVATIONS", url + "/backup")
    result = await api._observations_with_fallback("F700000103", grandeur)
    assert calls == ["/primary", "/backup"]
    assert result[-1].value == expected
    assert result[-1].source == "hubeau"
    assert result[-1].unit == ("m" if grandeur == "H" else "m³/s")


async def test_primary_success_does_not_call_backup(api):
    api.get_observations = AsyncMock(return_value=[obs()])
    api.get_hubeau_observations = AsyncMock()
    await api._observations_with_fallback("station", "H")
    api.get_hubeau_observations.assert_not_called()


@pytest.mark.parametrize("primary", [[], [obs(minutes=180)]])
async def test_empty_or_old_primary_tries_backup(api, primary):
    api.get_observations = AsyncMock(return_value=primary)
    api.get_hubeau_observations = AsyncMock(return_value=[obs(2, source="hubeau")])
    assert (await api._observations_with_fallback("station", "H"))[
        -1
    ].source == "hubeau"


async def test_older_backup_does_not_replace_primary(api):
    primary = [obs(minutes=180)]
    api.get_observations = AsyncMock(return_value=primary)
    api.get_hubeau_observations = AsyncMock(
        return_value=[obs(minutes=240, source="hubeau")]
    )
    assert await api._observations_with_fallback("station", "H") == primary
    api.get_hubeau_observations.side_effect = VigicruesAPIError("offline")
    assert await api._observations_with_fallback("station", "H") == primary


async def test_reject_wrong_backup_station_or_quantity(api):
    api._request = AsyncMock(
        return_value={
            "data": [
                {
                    "code_station": "OTHER",
                    "grandeur_hydro": "H",
                    "date_obs": datetime.now(UTC).isoformat(),
                    "resultat_obs": 1000,
                },
            ]
        }
    )
    with pytest.raises(VigicruesAPIError):
        await api.get_hubeau_observations("station", "H")


def test_observation_sorting_invalid_values_and_trend():
    now = datetime.now(UTC)
    data = [
        {"DtObsHydro": (now - timedelta(minutes=i)).isoformat(), "ResObsHydro": value}
        for i, value in [(0, 1.3), (10, 1.0), (5, 1.1)]
    ]
    data += [
        {"DtObsHydro": now.isoformat()},
        {"DtObsHydro": now.isoformat(), "ResObsHydro": "NaN"},
    ]
    result = VigicruesAPI._observations(data, "H")
    assert [o.value for o in result] == [1, 1.1, 1.3]
    assert VigicruesAPI._calculate_tendance(result) == "hausse"
    assert VigicruesAPI._calculate_tendance([obs(-1), obs(-1)]) == "stable"


async def test_partial_failures_do_not_erase_good_resources(api):
    api._observations_with_fallback = AsyncMock(
        side_effect=[[obs()], VigicruesAPIError("Q down")]
    )
    api.get_previsions = AsyncMock(side_effect=VigicruesAPIError("forecasts down"))
    api.get_vigilance_levels = AsyncMock(return_value={"IF7": "Orange"})
    result = await api.get_station_data(Station("station", "Test", troncon_id="IF7"))
    assert result.hauteur.value == 1
    assert result.vigilance_level == "Orange"
    assert result.debit is None
    assert set(result.errors) == {"debit", "hauteur_previsions", "debit_previsions"}


async def test_programming_errors_are_not_silently_hidden(api):
    api._observations_with_fallback = AsyncMock(side_effect=RuntimeError("bug"))
    api.get_previsions = AsyncMock(return_value=[])
    with pytest.raises(RuntimeError, match="bug"):
        await api.get_station_data(Station("station", "Test"))


@pytest.mark.parametrize(
    "payload", [None, [], {}, {"Serie": None}, {"Serie": {"ObssHydro": "invalid"}}]
)
async def test_malformed_primary_payload_can_trigger_backup(api, payload):
    api._request = AsyncMock(return_value=payload)
    api.get_hubeau_observations = AsyncMock(return_value=[obs(source="hubeau")])
    assert (await api._observations_with_fallback("station", "H"))[
        -1
    ].source == "hubeau"


async def test_malformed_vigilance_is_an_expected_api_error(api):
    api._request = AsyncMock(
        return_value={"features": [None, {"properties": None}, {"properties": []}]}
    )
    with pytest.raises(VigicruesAPIError):
        await api.get_vigilance_levels()
