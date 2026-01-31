"""API client for Vigicrues."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from .const import (
    ENDPOINT_OBSERVATIONS,
    ENDPOINT_PREVISIONS,
    ENDPOINT_STATIONS,
    ENDPOINT_TERRITORIES,
    ENDPOINT_TRONCONS,
    ENDPOINT_VIGILANCE,
    VIGILANCE_LEVELS,
)

_LOGGER = logging.getLogger(__name__)

# Request timeout in seconds
REQUEST_TIMEOUT = 30


@dataclass
class Territory:
    """Representation of a Vigicrues territory."""

    id: str
    name: str
    type: int = 5


@dataclass
class Troncon:
    """Representation of a Vigicrues troncon (river section)."""

    id: str
    name: str
    territory_id: str
    vigilance_level: int | None = None


@dataclass
class Station:
    """Representation of a Vigicrues station."""

    id: str
    name: str
    cours_eau: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    troncon_id: str | None = None
    troncon_name: str | None = None
    territory_id: str | None = None


@dataclass
class Observation:
    """Representation of an observation (height or flow)."""

    value: float
    timestamp: datetime
    unit: str


@dataclass
class Prevision:
    """Representation of a forecast."""

    value: float
    timestamp: datetime
    unit: str
    min_value: float | None = None
    max_value: float | None = None


@dataclass
class StationData:
    """Complete data for a station."""

    station: Station
    hauteur: Observation | None = None
    debit: Observation | None = None
    hauteur_previsions: list[Prevision] | None = None
    debit_previsions: list[Prevision] | None = None
    vigilance_level: str | None = None
    tendance_hauteur: str | None = None
    tendance_debit: str | None = None


class VigicruesAPIError(Exception):
    """Exception for Vigicrues API errors."""


class VigicruesAPI:
    """Client for the Vigicrues API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the API client."""
        self._session = session

    async def _request(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Make a request to the API."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(url, params=params) as response:
                    if response.status != 200:
                        raise VigicruesAPIError(
                            f"API request failed with status {response.status}"
                        )
                    return await response.json()
        except asyncio.TimeoutError as err:
            raise VigicruesAPIError("API request timed out") from err
        except aiohttp.ClientError as err:
            raise VigicruesAPIError(f"API request failed: {err}") from err

    async def get_territories(self) -> list[Territory]:
        """Get all territories."""
        data = await self._request(ENDPOINT_TERRITORIES)
        territories = []

        if "ListEntViworkaroundgiCru" in data:
            for item in data["ListEntVigiCru"]:
                territories.append(
                    Territory(
                        id=item.get("CdEntVigiCru", ""),
                        name=item.get("LbEntVigiCru", ""),
                    )
                )

        return territories

    async def get_territories_with_details(self) -> list[Territory]:
        """Get all territories with full details."""
        data = await self._request(ENDPOINT_TERRITORIES)
        territories = []

        # The API returns a flat list when no parameters are given
        if isinstance(data, dict) and "ListEntVigiCru" in data:
            for item in data["ListEntVigiCru"]:
                territories.append(
                    Territory(
                        id=str(item.get("CdEntVigiCru", "")),
                        name=item.get("LbEntVigiCru", ""),
                    )
                )
        elif isinstance(data, list):
            for item in data:
                territories.append(
                    Territory(
                        id=str(item.get("CdEntVigiCru", "")),
                        name=item.get("LbEntVigiCru", ""),
                    )
                )

        return territories

    async def get_troncons(self, territory_id: str | None = None) -> list[Troncon]:
        """Get troncons, optionally filtered by territory."""
        params = {}
        if territory_id:
            params["CdEntVigiCru"] = territory_id
            params["TypEntVigiCru"] = "5"

        data = await self._request(ENDPOINT_TRONCONS, params)
        troncons = []

        def extract_troncons(items: list, ter_id: str = "") -> None:
            for item in items:
                if "ListEntVigiCru" in item:
                    # Nested structure - contains troncons
                    for troncon in item["ListEntVigiCru"]:
                        troncons.append(
                            Troncon(
                                id=str(troncon.get("CdEntVigiCru", "")),
                                name=troncon.get("LbEntVigiCru", ""),
                                territory_id=ter_id or str(item.get("CdEntVigiCru", "")),
                            )
                        )
                else:
                    troncons.append(
                        Troncon(
                            id=str(item.get("CdEntVigiCru", "")),
                            name=item.get("LbEntVigiCru", ""),
                            territory_id=ter_id,
                        )
                    )

        if isinstance(data, dict):
            if "ListEntVigiCru" in data:
                extract_troncons(data["ListEntVigiCru"], territory_id or "")
            elif "Territoire" in data:
                # Detailed response
                if "ListEntVigiCru" in data["Territoire"]:
                    extract_troncons(
                        data["Territoire"]["ListEntVigiCru"],
                        str(data["Territoire"].get("CdEntVigiCru", "")),
                    )
        elif isinstance(data, list):
            extract_troncons(data, territory_id or "")

        return troncons

    async def get_stations(
        self, territory_id: str | None = None, troncon_id: str | None = None
    ) -> list[Station]:
        """Get stations, optionally filtered by territory or troncon."""
        params = {}
        if territory_id:
            params["CdEntVigiCru"] = territory_id
            params["TypEntVigiCru"] = "5"
        elif troncon_id:
            params["CdEntVigiCru"] = troncon_id
            params["TypEntVigiCru"] = "8"

        data = await self._request(ENDPOINT_STATIONS, params)
        stations = []

        def extract_stations_from_dict(item: dict, tron_id: str = "", tron_name: str = "", ter_id: str = "") -> None:
            """Extract station information from a dictionary item."""
            # Check if this item contains stations in aNMoinsUn field (hierarchical structure)
            if "aNMoinsUn" in item and isinstance(item["aNMoinsUn"], list):
                for sub_item in item["aNMoinsUn"]:
                    # These are troncons (type 8), treat them as stations
                    if sub_item.get("TypEntVigiCruInferieur") == "8":
                        station_id = sub_item.get("CdEntVigiCruInferieur", "")
                        station_name = sub_item.get("LbEntVigiCruInferieur", "")
                        if station_id and station_name:
                            stations.append(
                                Station(
                                    id=str(station_id),
                                    name=station_name,
                                    troncon_id=tron_id or item.get("CdEntVigiCru"),
                                    troncon_name=tron_name or item.get("LbEntVigiCru"),
                                    territory_id=ter_id,
                                )
                            )
            
            # Also check ListEntVigiCru (standard structure)
            if "ListEntVigiCru" in item:
                for sub_item in item["ListEntVigiCru"]:
                    if isinstance(sub_item, dict):
                        if "ListEntVigiCru" in sub_item:
                            # This is a troncon containing stations
                            nested_tron_id = str(sub_item.get("CdEntVigiCru", ""))
                            nested_tron_name = sub_item.get("LbEntVigiCru", "")
                            extract_stations_from_dict(
                                sub_item,
                                nested_tron_id,
                                nested_tron_name,
                                ter_id,
                            )
                        elif "CdStationHydro" in sub_item or "CdEntVigiCru" in sub_item:
                            # This is a station
                            station_id = sub_item.get("CdStationHydro") or sub_item.get("CdEntVigiCru", "")
                            stations.append(
                                Station(
                                    id=str(station_id),
                                    name=sub_item.get("LbStationHydro") or sub_item.get("LbEntVigiCru", ""),
                                    cours_eau=sub_item.get("LbCoursEau"),
                                    latitude=sub_item.get("CoordStationHydro", {}).get("Y") if isinstance(sub_item.get("CoordStationHydro"), dict) else None,
                                    longitude=sub_item.get("CoordStationHydro", {}).get("X") if isinstance(sub_item.get("CoordStationHydro"), dict) else None,
                                    troncon_id=tron_id,
                                    troncon_name=tron_name,
                                    territory_id=ter_id,
                                )
                            )

        if isinstance(data, dict):
            if "Territoire" in data:
                ter_id = str(data["Territoire"].get("CdEntVigiCru", ""))
                extract_stations_from_dict(data["Territoire"], ter_id=ter_id)
            elif "Troncon" in data:
                tron_id = str(data["Troncon"].get("CdEntVigiCru", ""))
                tron_name = data["Troncon"].get("LbEntVigiCru", "")
                extract_stations_from_dict(data["Troncon"], tron_id, tron_name)
            elif "ListEntVigiCru" in data:
                # Handle list of items at root level
                for item in data["ListEntVigiCru"]:
                    if isinstance(item, dict):
                        ter_id = str(item.get("CdEntVigiCru", ""))
                        extract_stations_from_dict(item, ter_id=ter_id)

        return stations

    async def get_station_details(self, station_id: str) -> Station | None:
        """Get details for a specific station."""
        params = {
            "CdEntVigiCru": station_id,
            "TypEntVigiCru": "7",
        }
        data = await self._request(ENDPOINT_STATIONS, params)

        if isinstance(data, dict) and "Station" in data:
            station_data = data["Station"]
            coord = station_data.get("CoordStationHydro", {})
            return Station(
                id=str(station_data.get("CdStationHydro", station_id)),
                name=station_data.get("LbStationHydro", ""),
                cours_eau=station_data.get("LbCoursEau"),
                latitude=coord.get("Y") if isinstance(coord, dict) else None,
                longitude=coord.get("X") if isinstance(coord, dict) else None,
                troncon_id=station_data.get("CdTronVigiCru"),
                troncon_name=station_data.get("LbTronVigiCru"),
            )

        return None

    async def get_observations(
        self, station_id: str, grandeur: str = "H"
    ) -> list[Observation]:
        """Get observations for a station.

        Args:
            station_id: The station ID
            grandeur: "H" for height, "Q" for flow

        Returns:
            List of observations
        """
        params = {
            "CdStationHydro": station_id,
            "GrdSerie": grandeur,
            "FormatDate": "iso",
        }
        data = await self._request(ENDPOINT_OBSERVATIONS, params)
        observations = []

        # Parse the observations
        if isinstance(data, dict) and "Serie" in data:
            serie = data["Serie"]
            obs_list = serie.get("ObssHydro", [])
            unit = "m" if grandeur == "H" else "m³/s"

            for obs in obs_list:
                try:
                    timestamp = datetime.fromisoformat(
                        obs.get("DtObsHydro", "").replace("Z", "+00:00")
                    )
                    value = float(obs.get("ResObsHydro", 0))
                    observations.append(
                        Observation(value=value, timestamp=timestamp, unit=unit)
                    )
                except (ValueError, TypeError) as err:
                    _LOGGER.debug("Failed to parse observation: %s", err)

        return observations

    async def get_previsions(
        self, station_id: str, grandeur: str = "H"
    ) -> list[Prevision]:
        """Get forecasts for a station.

        Args:
            station_id: The station ID
            grandeur: "H" for height, "Q" for flow

        Returns:
            List of forecasts
        """
        params = {
            "CdEntVigiCru": station_id,
            "TypEntVigiCru": "7",
            "GrdSimul": grandeur,
            "FormatDate": "iso",
        }
        data = await self._request(ENDPOINT_PREVISIONS, params)
        previsions = []

        # Parse the previsions
        if isinstance(data, dict):
            simulations = data.get("ListSimul", [])
            unit = "m" if grandeur == "H" else "m³/s"

            for simul in simulations:
                prev_list = simul.get("ListPrev", [])
                for prev in prev_list:
                    try:
                        timestamp = datetime.fromisoformat(
                            prev.get("DtPrev", "").replace("Z", "+00:00")
                        )
                        value = float(prev.get("ResPrev", 0))
                        min_val = prev.get("ResMinPrev")
                        max_val = prev.get("ResMaxPrev")
                        previsions.append(
                            Prevision(
                                value=value,
                                timestamp=timestamp,
                                unit=unit,
                                min_value=float(min_val) if min_val else None,
                                max_value=float(max_val) if max_val else None,
                            )
                        )
                    except (ValueError, TypeError) as err:
                        _LOGGER.debug("Failed to parse prevision: %s", err)

        return previsions

    async def get_vigilance_levels(self) -> dict[str, str]:
        """Get current vigilance levels for all troncons.

        Returns:
            Dictionary mapping troncon ID to vigilance level name
        """
        data = await self._request(ENDPOINT_VIGILANCE)
        levels = {}

        if isinstance(data, dict) and "features" in data:
            for feature in data["features"]:
                props = feature.get("properties", {})
                troncon_id = props.get("CdEntVigiCru")
                niveau = props.get("NivSituVigiCruEnt")
                if troncon_id and niveau:
                    levels[str(troncon_id)] = VIGILANCE_LEVELS.get(niveau, "Inconnu")

        return levels

    async def get_station_data(self, station: Station) -> StationData:
        """Get all data for a station.

        Args:
            station: The station object

        Returns:
            Complete station data including observations, forecasts, and vigilance
        """
        # Fetch all data in parallel
        hauteur_obs_task = self.get_observations(station.id, "H")
        debit_obs_task = self.get_observations(station.id, "Q")
        hauteur_prev_task = self.get_previsions(station.id, "H")
        debit_prev_task = self.get_previsions(station.id, "Q")
        vigilance_task = self.get_vigilance_levels()

        results = await asyncio.gather(
            hauteur_obs_task,
            debit_obs_task,
            hauteur_prev_task,
            debit_prev_task,
            vigilance_task,
            return_exceptions=True,
        )

        hauteur_obs = results[0] if not isinstance(results[0], Exception) else []
        debit_obs = results[1] if not isinstance(results[1], Exception) else []
        hauteur_prev = results[2] if not isinstance(results[2], Exception) else []
        debit_prev = results[3] if not isinstance(results[3], Exception) else []
        vigilance_levels = results[4] if not isinstance(results[4], Exception) else {}

        # Get latest observations
        latest_hauteur = hauteur_obs[-1] if hauteur_obs else None
        latest_debit = debit_obs[-1] if debit_obs else None

        # Calculate tendance (trend) based on last few observations
        tendance_hauteur = self._calculate_tendance(hauteur_obs)
        tendance_debit = self._calculate_tendance(debit_obs)

        # Get vigilance level for this station's troncon
        vigilance_level = None
        if station.troncon_id and station.troncon_id in vigilance_levels:
            vigilance_level = vigilance_levels[station.troncon_id]

        return StationData(
            station=station,
            hauteur=latest_hauteur,
            debit=latest_debit,
            hauteur_previsions=hauteur_prev if hauteur_prev else None,
            debit_previsions=debit_prev if debit_prev else None,
            vigilance_level=vigilance_level,
            tendance_hauteur=tendance_hauteur,
            tendance_debit=tendance_debit,
        )

    def _calculate_tendance(
        self, observations: list[Observation], sample_size: int = 5
    ) -> str | None:
        """Calculate the trend based on recent observations.

        Args:
            observations: List of observations (should be sorted by time)
            sample_size: Number of observations to consider

        Returns:
            Trend: "hausse", "baisse", or "stable"
        """
        if len(observations) < 2:
            return None

        # Take the last few observations
        recent = observations[-sample_size:] if len(observations) >= sample_size else observations

        if len(recent) < 2:
            return None

        # Calculate the difference between first and last
        first_value = recent[0].value
        last_value = recent[-1].value
        diff = last_value - first_value

        # Define threshold for "stable" (1% of the value or 0.01m for small values)
        threshold = max(abs(first_value) * 0.01, 0.01)

        if diff > threshold:
            return "hausse"
        elif diff < -threshold:
            return "baisse"
        else:
            return "stable"
