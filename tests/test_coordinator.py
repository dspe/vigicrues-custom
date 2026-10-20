"""Regression tests for retention, restarts, recovery and sensor semantics."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import UnitOfVolumeFlowRate
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.vigicrues.api import (
    Observation,
    Prevision,
    Station,
    StationData,
    VigicruesAPIError,
)
from custom_components.vigicrues.cache import deserialize, serialize
from custom_components.vigicrues.coordinator import merge_data
from custom_components.vigicrues.sensor import (
    SENSOR_DESCRIPTIONS,
    VigicruesSensor,
    get_hauteur_extra_attrs,
)

RESOURCES = ("hauteur", "debit", "hauteur_previsions", "debit_previsions", "vigilance")


def snapshot():
    now = datetime.now(UTC)
    return StationData(
        station=Station(
            "F700000103", "Paris", latitude=0, longitude=0, troncon_id="IF7"
        ),
        hauteur=Observation(0.9, now, "m"),
        debit=Observation(120, now, "m³/s"),
        hauteur_previsions=[Prevision(1, now + timedelta(hours=1), "m", 0, 2)],
        vigilance_level="Orange",
        tendance_hauteur="hausse",
        tendance_debit="stable",
        last_success={key: now for key in RESOURCES},
        last_attempt=now,
    )


def outage():
    return StationData(
        station=snapshot().station,
        errors={key: "offline" for key in RESOURCES},
        last_attempt=datetime.now(UTC),
    )


async def test_outage_then_recovery(coordinator):
    initial = snapshot()
    recovered = snapshot()
    recovered.hauteur.value = 1.1
    coordinator.api.get_station_data.side_effect = [initial, outage(), recovered]
    first = await coordinator._async_update_data()
    failed = await coordinator._async_update_data()
    assert failed.hauteur == first.hauteur
    assert failed.vigilance_level == "Orange"
    assert failed.status(datetime.now(UTC)) == "stale"
    good = await coordinator._async_update_data()
    assert good.hauteur.value == 1.1
    assert good.status(datetime.now(UTC)) == "ok"
    assert good.errors == {}
    assert coordinator._store.async_save.await_count == 3


async def test_restart_during_total_outage_uses_cache(coordinator):
    initial = snapshot()
    coordinator._store.async_load.return_value = serialize(initial)
    coordinator.api.get_station_details.side_effect = VigicruesAPIError(
        "metadata offline"
    )
    coordinator.api.get_station_data.return_value = outage()
    await coordinator.async_config_entry_first_refresh()
    assert coordinator.last_update_success
    assert coordinator.data.hauteur == initial.hauteur
    assert coordinator.data.status(datetime.now(UTC)) == "stale"
    sensor = VigicruesSensor(
        coordinator, next(d for d in SENSOR_DESCRIPTIONS if d.key == "hauteur")
    )
    assert sensor.available
    assert sensor.native_value == 0.9
    assert sensor.extra_state_attributes["data_stale"]
    assert (
        sensor.extra_state_attributes["timestamp"]
        == initial.hauteur.timestamp.isoformat()
    )


async def test_first_start_without_data_uses_ha_retry(coordinator):
    coordinator.api.get_station_details.side_effect = VigicruesAPIError(
        "metadata offline"
    )
    coordinator.api.get_station_data.return_value = outage()
    with pytest.raises(ConfigEntryNotReady):
        await coordinator.async_config_entry_first_refresh()


async def test_metadata_failure_does_not_block_hubeau(coordinator):
    initial = snapshot()
    initial.hauteur.source = "hubeau"
    coordinator.api.get_station_details.side_effect = VigicruesAPIError(
        "metadata offline"
    )
    coordinator.api.get_station_data.return_value = initial
    result = await coordinator._async_update_data()
    assert result.hauteur.source == "hubeau"
    assert result.status(datetime.now(UTC)) == "degraded"
    assert not coordinator._details_loaded


async def test_metadata_retry_and_config_section_wins(coordinator):
    coordinator.api.get_station_details.side_effect = [
        VigicruesAPIError("offline"),
        Station("F700000103", "Paris", cours_eau="Seine"),
    ]
    coordinator.api.get_station_data.side_effect = [snapshot(), snapshot()]
    await coordinator._async_update_data()
    await coordinator._async_update_data()
    assert coordinator.station.troncon_id == "IF7"
    assert coordinator.station.cours_eau == "Seine"
    assert coordinator._details_loaded


async def test_corrupt_cache_is_ignored(coordinator):
    coordinator._store.async_load.return_value = {"station": {"unexpected": True}}
    coordinator.api.get_station_data.return_value = snapshot()
    assert (await coordinator._async_update_data()).hauteur.value == 0.9


async def test_disk_failure_does_not_hide_data(coordinator):
    coordinator.api.get_station_data.return_value = snapshot()
    coordinator._store.async_save.side_effect = OSError("disk full")
    assert (await coordinator._async_update_data()).hauteur.value == 0.9


def test_merge_is_partial_and_never_rolls_measurements_back():
    previous = snapshot()
    current = snapshot()
    current.hauteur = replace(
        previous.hauteur,
        timestamp=previous.hauteur.timestamp - timedelta(hours=1),
        value=0.1,
    )
    current.debit = replace(
        previous.debit,
        timestamp=previous.debit.timestamp + timedelta(minutes=5),
        value=125,
    )
    current.errors = {"hauteur_previsions": "offline"}
    result = merge_data(current, previous)
    assert result.hauteur == previous.hauteur
    assert result.debit.value == 125
    assert "hauteur" in result.errors
    assert result.hauteur_previsions == previous.hauteur_previsions
    assert result.last_success["hauteur"] == previous.last_success["hauteur"]


def test_successful_empty_forecasts_clear_previous_forecasts():
    previous = snapshot()
    current = snapshot()
    current.hauteur_previsions = []
    assert merge_data(current, previous).hauteur_previsions == []
    previous.hauteur_previsions[0].timestamp = datetime.now(UTC) - timedelta(minutes=1)
    assert merge_data(outage(), previous).hauteur_previsions == []


def test_cache_roundtrip_and_station_guard():
    previous = snapshot()
    restored = deserialize(serialize(previous), previous.station.id)
    assert restored.hauteur == previous.hauteur
    assert restored.hauteur_previsions == previous.hauteur_previsions
    assert restored.status(datetime.now(UTC)) == "stale"
    with pytest.raises(ValueError):
        deserialize(serialize(previous), "OTHER")


def test_old_measurements_with_http_success_are_still_stale():
    data = snapshot()
    now = datetime.now(UTC)
    data.hauteur.timestamp = now - timedelta(hours=3)
    assert data.resource_stale("hauteur", now)
    assert data.status(now) == "degraded"
    data.debit.timestamp = data.hauteur.timestamp
    data.last_success["vigilance"] = data.hauteur.timestamp
    assert data.status(now) == "stale"


async def test_sensor_units_zero_coordinates_and_zero_bounds(coordinator):
    data = snapshot()
    coordinator.data = data
    description = next(d for d in SENSOR_DESCRIPTIONS if d.key == "debit")
    assert (
        description.native_unit_of_measurement
        == UnitOfVolumeFlowRate.CUBIC_METERS_PER_SECOND
    )
    sensor = VigicruesSensor(coordinator, description)
    assert sensor.native_value == 120
    assert sensor.extra_state_attributes["latitude"] == 0
    assert sensor.extra_state_attributes["longitude"] == 0
    assert get_hauteur_extra_attrs(data)["previsions"][0]["min"] == 0
    data.debit = None
    assert not sensor.available


def test_options_flow_uses_read_only_home_assistant_config_entry():
    from custom_components.vigicrues.config_flow import VigicruesConfigFlow

    assert VigicruesConfigFlow.async_get_options_flow(None) is not None


async def test_persistent_storage_survives_new_coordinator(hass, entry):
    """Exercise Home Assistant's real on-disk Store across coordinator instances."""
    from unittest.mock import patch

    from custom_components.vigicrues.coordinator import VigicruesDataUpdateCoordinator

    with patch("custom_components.vigicrues.coordinator.async_get_clientsession"):
        first = VigicruesDataUpdateCoordinator(hass, entry)
        second = VigicruesDataUpdateCoordinator(hass, entry)
    first.api.get_station_details = AsyncMock(return_value=None)
    first.api.get_station_data = AsyncMock(return_value=snapshot())
    second.api.get_station_details = AsyncMock(side_effect=VigicruesAPIError("offline"))
    second.api.get_station_data = AsyncMock(return_value=outage())
    try:
        initial = await first._async_update_data()
        await first.async_shutdown()
        restored = await second._async_update_data()
        assert restored.hauteur == initial.hauteur
        assert restored.vigilance_level == initial.vigilance_level
        assert restored.resource_stale("vigilance", datetime.now(UTC))
        await second.async_remove_cache()
        assert await second._store.async_load() is None
    finally:
        await first.async_shutdown()
        await second.async_shutdown()


async def test_configuration_forms_can_retry_after_catalogue_failure(hass):
    """Empty retry forms must not assume a previous station/territory selection."""
    from unittest.mock import patch

    from custom_components.vigicrues.api import Territory
    from custom_components.vigicrues.config_flow import VigicruesConfigFlow

    flow = VigicruesConfigFlow()
    flow.hass = hass
    with (
        patch("custom_components.vigicrues.config_flow.async_get_clientsession"),
        patch("custom_components.vigicrues.config_flow.VigicruesAPI") as api,
    ):
        api.return_value.get_territories_with_details = AsyncMock(
            side_effect=[VigicruesAPIError("offline"), [Territory("4", "Seine aval")]]
        )
        failed = await flow.async_step_user()
        assert failed["errors"] == {"base": "cannot_connect"}
        retried = await flow.async_step_user({})
        assert retried["errors"] == {}
        flow._selected_territory_id = "4"
        api.return_value.get_stations = AsyncMock(
            side_effect=[VigicruesAPIError("offline"), [Station("F700000103", "Paris")]]
        )
        failed = await flow.async_step_station()
        assert failed["errors"] == {"base": "cannot_connect"}
        retried = await flow.async_step_station({})
        assert retried["errors"] == {}


async def test_card_discovery_attributes_survive_entity_renaming(coordinator):
    coordinator.data = snapshot()
    for description in SENSOR_DESCRIPTIONS:
        sensor = VigicruesSensor(coordinator, description)
        assert sensor.extra_state_attributes["integration"] == "vigicrues"
        assert sensor.extra_state_attributes["sensor_type"] == description.key
