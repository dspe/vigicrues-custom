"""Poll independently, preserve partial results, and persist the last good values."""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Station, StationData, VigicruesAPI, VigicruesAPIError
from .cache import deserialize, serialize
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TERRITORY_ID,
    CONF_TRONCON_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def merge_data(current: StationData, previous: StationData | None) -> StationData:
    """Keep failed resources, never move observations backwards in time."""
    if previous is not None:
        current.last_success = {**previous.last_success, **current.last_success}
        for resource in ("hauteur", "debit"):
            old, new = getattr(previous, resource), getattr(current, resource)
            if resource in current.errors or (
                old and new and old.timestamp > new.timestamp
            ):
                setattr(current, resource, old)
                setattr(
                    current,
                    f"tendance_{resource}",
                    getattr(previous, f"tendance_{resource}"),
                )
                if resource not in current.errors:
                    current.errors[resource] = (
                        "Received observations older than cached measurement"
                    )
                if resource in previous.last_success:
                    current.last_success[resource] = previous.last_success[resource]
        for resource in ("hauteur_previsions", "debit_previsions", "vigilance"):
            if resource in current.errors:
                field = "vigilance_level" if resource == "vigilance" else resource
                setattr(current, field, getattr(previous, field))
    now = current.last_attempt or datetime.now(UTC)
    for resource in ("hauteur_previsions", "debit_previsions"):
        setattr(
            current,
            resource,
            [p for p in getattr(current, resource) or [] if p.timestamp > now],
        )
    return current


class VigicruesDataUpdateCoordinator(DataUpdateCoordinator[StationData]):
    """Manage a single configured station without losing values during outages."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.api = VigicruesAPI(async_get_clientsession(hass))
        self.station_id = entry.data[CONF_STATION_ID]
        self.station_name = entry.data.get(CONF_STATION_NAME, self.station_id)
        self.troncon_id = entry.data.get(CONF_TRONCON_ID)
        self._territory_id = entry.data.get(CONF_TERRITORY_ID)
        scan = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )
        if not isinstance(scan, (int, float)) or not math.isfinite(scan):
            scan = DEFAULT_SCAN_INTERVAL.total_seconds()
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{self.station_id}",
            update_interval=timedelta(
                seconds=max(scan, MIN_SCAN_INTERVAL.total_seconds())
            ),
        )
        self._station = Station(
            id=self.station_id,
            name=self.station_name,
            troncon_id=self.troncon_id,
            territory_id=self._territory_id,
        )
        self._details_loaded = False
        self._cache_loaded = False
        self._previous: StationData | None = None
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._health: str | None = None

    @property
    def station(self) -> Station:
        return self._station

    async def _async_update_data(self) -> StationData:
        if not self._cache_loaded:
            self._cache_loaded = True
            try:
                payload = await self._store.async_load()
                if payload:
                    self._previous = deserialize(payload, self.station_id)
                    self._station = self._previous.station
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                _LOGGER.warning(
                    "Unable to restore Vigicrues cache for %s", self.station_id
                )

        # Metadata failures must never prevent observation fallback or cached startup.
        if not self._details_loaded:
            try:
                station = await self.api.get_station_details(self.station_id)
                if station:
                    self._station = replace(
                        station,
                        troncon_id=self.troncon_id or station.troncon_id,
                        troncon_name=self._station.troncon_name or station.troncon_name,
                        territory_id=self._territory_id or station.territory_id,
                    )
                    self._details_loaded = True
            except VigicruesAPIError as err:
                _LOGGER.debug("Station details unavailable: %s", err)

        current = merge_data(
            await self.api.get_station_data(self._station), self._previous
        )
        if not current.has_values:
            raise UpdateFailed(
                "No observations or vigilance available from Vigicrues, Hub'Eau or cache"
            )

        health = current.status(datetime.now(UTC))
        if health != self._health:
            if health != "ok":
                _LOGGER.warning(
                    "Station %s: %s (see sensor attributes for freshness and errors)",
                    self.station_id,
                    health,
                )
            elif self._health is not None:
                _LOGGER.info(
                    "Station %s: normal data collection restored", self.station_id
                )
            self._health = health
        self._previous = current
        try:
            await self._store.async_save(serialize(current))
        except OSError:
            _LOGGER.warning("Unable to save Vigicrues cache for %s", self.station_id)
        return current

    async def async_remove_cache(self) -> None:
        """Remove retained measurements only when the entry is deleted."""
        await self._store.async_remove()
