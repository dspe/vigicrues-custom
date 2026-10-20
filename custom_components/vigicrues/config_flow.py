"""Config flow for Vigicrues integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VigicruesAPI, VigicruesAPIError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TERRITORY_ID,
    CONF_TERRITORY_NAME,
    CONF_TRONCON_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class VigicruesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vigicrues."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._territories: dict[str, str] = {}
        self._stations: dict[str, dict[str, Any]] = {}
        self._selected_territory_id: str | None = None
        self._selected_territory_name: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - select territory."""
        errors: dict[str, str] = {}

        if user_input is not None and "territory" in user_input:
            self._selected_territory_id = user_input["territory"]
            self._selected_territory_name = self._territories.get(
                user_input["territory"], ""
            )
            return await self.async_step_station()

        # Fetch territories
        try:
            api = VigicruesAPI(async_get_clientsession(self.hass))
            territories = await api.get_territories_with_details()
            self._territories = {t.id: t.name for t in territories}
        except VigicruesAPIError as err:
            _LOGGER.error("Failed to fetch territories: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if not self._territories:
            errors["base"] = "no_territories"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        # Sort territories by name
        sorted_territories = dict(sorted(self._territories.items(), key=lambda x: x[1]))

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("territory"): vol.In(sorted_territories),
                }
            ),
            errors=errors,
        )

    async def async_step_station(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the station selection step."""
        errors: dict[str, str] = {}

        if user_input is not None and "station" in user_input:
            station_id = user_input["station"]
            station_info = self._stations.get(station_id, {})

            # Check if this station is already configured
            await self.async_set_unique_id(station_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=station_info.get("name", station_id),
                data={
                    CONF_STATION_ID: station_id,
                    CONF_STATION_NAME: station_info.get("name", station_id),
                    CONF_TERRITORY_ID: self._selected_territory_id,
                    CONF_TERRITORY_NAME: self._selected_territory_name,
                    CONF_TRONCON_ID: station_info.get("troncon_id"),
                },
            )

        # Fetch stations for the selected territory
        try:
            api = VigicruesAPI(async_get_clientsession(self.hass))
            stations = await api.get_stations(territory_id=self._selected_territory_id)

            self._stations = {}
            for s in stations:
                display_name = s.name
                if s.cours_eau:
                    display_name = f"{s.name} ({s.cours_eau})"
                if s.troncon_name:
                    display_name = f"{display_name} - {s.troncon_name}"

                self._stations[s.id] = {
                    "name": s.name,
                    "display_name": display_name,
                    "troncon_id": s.troncon_id,
                }

        except VigicruesAPIError as err:
            _LOGGER.error("Failed to fetch stations: %s", err)
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="station",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        if not self._stations:
            errors["base"] = "no_stations"
            return self.async_show_form(
                step_id="station",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        # Create options dict with display names
        station_options = {
            sid: info["display_name"] for sid, info in self._stations.items()
        }
        # Sort by display name
        sorted_stations = dict(sorted(station_options.items(), key=lambda x: x[1]))

        return self.async_show_form(
            step_id="station",
            data_schema=vol.Schema(
                {
                    vol.Required("station"): vol.In(sorted_stations),
                }
            ),
            errors=errors,
            description_placeholders={
                "territory": self._selected_territory_name or "",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return VigicruesOptionsFlow()


class VigicruesOptionsFlow(OptionsFlow):
    """Handle options flow for Vigicrues."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=int(current_interval),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=int(MIN_SCAN_INTERVAL.total_seconds())),
                    ),
                }
            ),
        )
