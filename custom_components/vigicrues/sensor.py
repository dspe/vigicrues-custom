"""Sensor platform for Vigicrues integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import StationData
from .const import (
    ATTR_COURS_EAU,
    ATTR_CRUES_HISTORIQUES,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_PREVISIONS,
    ATTR_STATION_ID,
    ATTR_STATION_NAME,
    ATTR_TIMESTAMP,
    ATTR_TRONCON,
    DOMAIN,
    SENSOR_TYPE_DEBIT,
    SENSOR_TYPE_HAUTEUR,
    SENSOR_TYPE_TENDANCE,
    SENSOR_TYPE_VIGILANCE,
)
from .coordinator import VigicruesDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class VigicruesSensorEntityDescription(SensorEntityDescription):
    """Describes a Vigicrues sensor entity."""

    value_fn: Callable[[StationData], Any]
    extra_attrs_fn: Callable[[StationData], dict[str, Any]] | None = None


def get_hauteur_value(data: StationData) -> float | None:
    """Get the water height value."""
    if data.hauteur:
        return round(data.hauteur.value, 2)
    return None


def get_debit_value(data: StationData) -> float | None:
    """Get the flow rate value."""
    if data.debit:
        return round(data.debit.value, 2)
    return None


def get_vigilance_value(data: StationData) -> str | None:
    """Get the vigilance level."""
    return data.vigilance_level


def get_tendance_hauteur_value(data: StationData) -> str | None:
    """Get the height trend."""
    return data.tendance_hauteur


def get_hauteur_extra_attrs(data: StationData) -> dict[str, Any]:
    """Get extra attributes for height sensor."""
    attrs: dict[str, Any] = {}

    if data.hauteur and data.hauteur.timestamp:
        attrs[ATTR_TIMESTAMP] = data.hauteur.timestamp.isoformat()

    if data.hauteur_previsions:
        attrs[ATTR_PREVISIONS] = [
            {
                "timestamp": p.timestamp.isoformat(),
                "value": round(p.value, 2),
                "min": round(p.min_value, 2) if p.min_value else None,
                "max": round(p.max_value, 2) if p.max_value else None,
            }
            for p in data.hauteur_previsions[:10]  # Limit to 10 forecasts
        ]

    return attrs


def get_debit_extra_attrs(data: StationData) -> dict[str, Any]:
    """Get extra attributes for flow sensor."""
    attrs: dict[str, Any] = {}

    if data.debit and data.debit.timestamp:
        attrs[ATTR_TIMESTAMP] = data.debit.timestamp.isoformat()

    if data.debit_previsions:
        attrs[ATTR_PREVISIONS] = [
            {
                "timestamp": p.timestamp.isoformat(),
                "value": round(p.value, 2),
                "min": round(p.min_value, 2) if p.min_value else None,
                "max": round(p.max_value, 2) if p.max_value else None,
            }
            for p in data.debit_previsions[:10]  # Limit to 10 forecasts
        ]

    return attrs


def get_vigilance_extra_attrs(data: StationData) -> dict[str, Any]:
    """Get extra attributes for vigilance sensor."""
    attrs: dict[str, Any] = {}

    if data.station.troncon_id:
        attrs[ATTR_TRONCON] = data.station.troncon_id
    if data.station.troncon_name:
        attrs["troncon_name"] = data.station.troncon_name

    return attrs


def get_tendance_extra_attrs(data: StationData) -> dict[str, Any]:
    """Get extra attributes for trend sensor."""
    attrs: dict[str, Any] = {}

    # Also include debit trend as an attribute
    if data.tendance_debit:
        attrs["tendance_debit"] = data.tendance_debit

    return attrs


SENSOR_DESCRIPTIONS: tuple[VigicruesSensorEntityDescription, ...] = (
    VigicruesSensorEntityDescription(
        key=SENSOR_TYPE_HAUTEUR,
        translation_key="hauteur",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_hauteur_value,
        extra_attrs_fn=get_hauteur_extra_attrs,
    ),
    VigicruesSensorEntityDescription(
        key=SENSOR_TYPE_DEBIT,
        translation_key="debit",
        native_unit_of_measurement=UnitOfVolumeFlowRate.CUBIC_METERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=get_debit_value,
        extra_attrs_fn=get_debit_extra_attrs,
    ),
    VigicruesSensorEntityDescription(
        key=SENSOR_TYPE_VIGILANCE,
        translation_key="vigilance",
        value_fn=get_vigilance_value,
        extra_attrs_fn=get_vigilance_extra_attrs,
    ),
    VigicruesSensorEntityDescription(
        key=SENSOR_TYPE_TENDANCE,
        translation_key="tendance",
        value_fn=get_tendance_hauteur_value,
        extra_attrs_fn=get_tendance_extra_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vigicrues sensors based on a config entry."""
    coordinator: VigicruesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        VigicruesSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    ]

    async_add_entities(entities)


class VigicruesSensor(CoordinatorEntity[VigicruesDataUpdateCoordinator], SensorEntity):
    """Representation of a Vigicrues sensor."""

    entity_description: VigicruesSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VigicruesDataUpdateCoordinator,
        description: VigicruesSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description

        self._attr_unique_id = f"{coordinator.station_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this station."""
        station = self.coordinator.data.station if self.coordinator.data else None

        identifiers = {(DOMAIN, self.coordinator.station_id)}

        device_info = DeviceInfo(
            identifiers=identifiers,
            name=self.coordinator.station_name,
            manufacturer="Vigicrues",
            model="Station hydrométrique",
            configuration_url=f"https://www.vigicrues.gouv.fr/station/{self.coordinator.station_id}",
        )

        if station and station.cours_eau:
            device_info["model"] = f"Station sur {station.cours_eau}"

        return device_info

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}

        if self.coordinator.data is None:
            return attrs

        data = self.coordinator.data
        station = data.station

        # Common attributes
        attrs[ATTR_STATION_ID] = station.id
        attrs[ATTR_STATION_NAME] = station.name

        if station.cours_eau:
            attrs[ATTR_COURS_EAU] = station.cours_eau
        if station.latitude:
            attrs[ATTR_LATITUDE] = station.latitude
        if station.longitude:
            attrs[ATTR_LONGITUDE] = station.longitude

        # Sensor-specific attributes
        if self.entity_description.extra_attrs_fn:
            attrs.update(self.entity_description.extra_attrs_fn(data))

        return attrs
