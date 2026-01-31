"""DataUpdateCoordinator for Vigicrues."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Station, StationData, VigicruesAPI, VigicruesAPIError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TRONCON_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class VigicruesDataUpdateCoordinator(DataUpdateCoordinator[StationData]):
    """Class to manage fetching Vigicrues data."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.api = VigicruesAPI(async_get_clientsession(hass))
        self.station_id: str = entry.data[CONF_STATION_ID]
        self.station_name: str = entry.data.get(CONF_STATION_NAME, self.station_id)
        self.troncon_id: str | None = entry.data.get(CONF_TRONCON_ID)

        # Get update interval from options or use default
        scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )
        if isinstance(scan_interval, (int, float)):
            update_interval = timedelta(seconds=scan_interval)
        else:
            update_interval = DEFAULT_SCAN_INTERVAL

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.station_id}",
            update_interval=update_interval,
        )

        # Station object (will be populated on first update)
        self._station: Station | None = None

    @property
    def station(self) -> Station | None:
        """Return the station object."""
        return self._station

    async def _async_update_data(self) -> StationData:
        """Fetch data from the API."""
        try:
            # Get or create station object
            if self._station is None:
                self._station = await self._get_station()

            if self._station is None:
                raise UpdateFailed(f"Station {self.station_id} not found")

            # Fetch all station data
            return await self.api.get_station_data(self._station)

        except VigicruesAPIError as err:
            raise UpdateFailed(f"Error communicating with Vigicrues API: {err}") from err

    async def _get_station(self) -> Station | None:
        """Get or create the station object."""
        # Try to get station details from API
        station = await self.api.get_station_details(self.station_id)

        if station:
            # Update troncon_id if we have one from config but not from API
            if self.troncon_id and not station.troncon_id:
                station.troncon_id = self.troncon_id
            return station

        # If API doesn't return details, create a basic station object
        return Station(
            id=self.station_id,
            name=self.station_name,
            troncon_id=self.troncon_id,
        )
