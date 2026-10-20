"""Vigicrues client with an independent Hub'Eau observation fallback."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    ENDPOINT_HUBEAU_OBSERVATIONS,
    ENDPOINT_OBSERVATIONS,
    ENDPOINT_PREVISIONS,
    ENDPOINT_STATIONS,
    ENDPOINT_TERRITORIES,
    ENDPOINT_TRONCONS,
    ENDPOINT_VIGILANCE,
    STALE_AFTER,
    VIGILANCE_LEVELS,
)

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = 15


@dataclass
class Territory:
    """Vigicrues territory."""

    id: str
    name: str
    type: int = 5


@dataclass
class Troncon:
    """River section."""

    id: str
    name: str
    territory_id: str
    vigilance_level: int | None = None


@dataclass
class Station:
    """Station metadata. Coordinates must be WGS84, never Lambert coordinates."""

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
    """Observation in metres or cubic metres per second."""

    value: float
    timestamp: datetime
    unit: str
    source: str = "vigicrues"


@dataclass
class Prevision:
    """Forecast in the same SI units as observations."""

    value: float
    timestamp: datetime
    unit: str
    min_value: float | None = None
    max_value: float | None = None


@dataclass
class StationData:
    """Partial station snapshot, including per-resource health information."""

    station: Station
    hauteur: Observation | None = None
    debit: Observation | None = None
    hauteur_previsions: list[Prevision] | None = None
    debit_previsions: list[Prevision] | None = None
    vigilance_level: str | None = None
    tendance_hauteur: str | None = None
    tendance_debit: str | None = None
    last_success: dict[str, datetime] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    last_attempt: datetime | None = None

    @property
    def has_values(self) -> bool:
        """Whether a snapshot contains something useful to display."""
        return any(
            x is not None for x in (self.hauteur, self.debit, self.vigilance_level)
        )

    def resource_stale(self, resource: str, now: datetime) -> bool:
        """A failed refresh or an old measurement is stale, even with HTTP 200."""
        if resource in self.errors:
            return True
        timestamp = self.last_success.get(resource)
        if resource in ("hauteur", "debit"):
            observation = getattr(self, resource)
            timestamp = observation.timestamp if observation else None
        return timestamp is None or now - timestamp > STALE_AFTER

    def status(self, now: datetime) -> str:
        """Summarize freshness of the values that are actually available."""
        resources = [key for key in ("hauteur", "debit") if getattr(self, key)]
        if self.vigilance_level is not None:
            resources.append("vigilance")
        if not resources or all(self.resource_stale(key, now) for key in resources):
            return "stale"
        if self.errors or any(self.resource_stale(key, now) for key in resources):
            return "degraded"
        if any(obs and obs.source == "hubeau" for obs in (self.hauteur, self.debit)):
            return "degraded"
        return "ok"


class VigicruesAPIError(Exception):
    """Expected network, service or payload error."""


def parse_datetime(value: Any) -> datetime:
    """Normalize API dates to aware UTC datetimes."""
    if not isinstance(value, str):
        raise ValueError("Missing ISO timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return result.astimezone(UTC)


def finite_float(value: Any) -> float:
    """Reject missing/non-finite measurements rather than inventing a zero."""
    if value is None or isinstance(value, bool):
        raise ValueError("Missing numeric value")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite numeric value")
    return result


def _items(data: Any) -> list[dict[str, Any]]:
    """Read the common reference response envelope."""
    items = data.get("ListEntVigiCru") if isinstance(data, dict) else data
    if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
        raise VigicruesAPIError("Invalid reference response")
    return items


def _identifier(value: Any) -> str | None:
    """Ignore placeholder identifiers returned by station detail responses."""
    if value is None or str(value).lower().startswith("a renseigner"):
        return None
    return str(value) or None


class VigicruesAPI:
    """Fetch observations, forecasts and official vigilance independently."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _request(self, url: str, params: dict[str, Any] | None = None) -> Any:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(url, params=params) as response:
                    # Hub'Eau uses 206 for a paginated result, including size=5.
                    if response.status not in (200, 206):
                        raise VigicruesAPIError(f"HTTP {response.status}")
                    data = await response.json()
                    if isinstance(data, dict) and str(data.get("code", "200")) not in (
                        "200",
                        "204",
                    ):
                        raise VigicruesAPIError(f"Service error: {data.get('code')}")
                    return data
        except TimeoutError as err:
            raise VigicruesAPIError("Request timed out") from err
        except (aiohttp.ClientError, ValueError, UnicodeError) as err:
            raise VigicruesAPIError(f"Invalid or inaccessible response: {err}") from err

    async def get_territories(self) -> list[Territory]:
        return await self.get_territories_with_details()

    async def get_territories_with_details(self) -> list[Territory]:
        data = await self._request(ENDPOINT_TERRITORIES)
        return [
            Territory(id=str(x["CdEntVigiCru"]), name=x["LbEntVigiCru"])
            for x in _items(data)
            if x.get("CdEntVigiCru") and x.get("LbEntVigiCru")
        ]

    async def get_troncons(self, territory_id: str | None = None) -> list[Troncon]:
        params = (
            {"CdEntVigiCru": territory_id, "TypEntVigiCru": "5"}
            if territory_id
            else None
        )
        data = await self._request(ENDPOINT_TRONCONS, params)
        return [
            Troncon(
                str(x["CdEntVigiCru"]),
                x["LbEntVigiCru"],
                territory_id
                or str(x.get("aNPlusUn", {}).get("CdEntVigiCruSuperieur", "")),
            )
            for x in _items(data)
            if x.get("CdEntVigiCru") and x.get("LbEntVigiCru")
        ]

    async def get_stations(
        self, territory_id: str | None = None, troncon_id: str | None = None
    ) -> list[Station]:
        params = {}
        if territory_id or troncon_id:
            params = {
                "CdEntVigiCru": territory_id or troncon_id,
                "TypEntVigiCru": "5" if territory_id else "8",
            }
        data = await self._request(ENDPOINT_STATIONS, params)
        stations: dict[str, Station] = {}
        # The official feed lists sections, with stations under aNMoinsUn.
        # Some station children incorrectly carry type 8 instead of type 7.
        for section in _items(data):
            if section.get("CdStationHydro"):
                station = self._station(section)
                stations[station.id] = station
                continue
            section_id = _identifier(section.get("CdEntVigiCru"))
            parent = section.get("aNPlusUn") or {}
            children = section.get("aNMoinsUn", [])
            if not isinstance(parent, dict) or not isinstance(children, list):
                raise VigicruesAPIError("Invalid station hierarchy")
            for child in children:
                if not isinstance(child, dict):
                    raise VigicruesAPIError("Invalid station entry")
                station_id = _identifier(child.get("CdEntVigiCruInferieur"))
                name = child.get("LbEntVigiCruInferieur")
                if station_id and name:
                    stations[station_id] = Station(
                        id=station_id,
                        name=name,
                        troncon_id=section_id,
                        troncon_name=section.get("LbEntVigiCru"),
                        territory_id=territory_id
                        or _identifier(parent.get("CdEntVigiCruSuperieur")),
                    )
        return list(stations.values())

    @staticmethod
    def _station(item: dict[str, Any]) -> Station:
        parent = item.get("aNPlusUn") or {}
        coord = item.get("CoordStationHydro") or {}
        if not isinstance(parent, dict) or not isinstance(coord, dict):
            raise VigicruesAPIError("Invalid station metadata")
        # CoordXStationHydro/CoordYStationHydro are Lambert-93, not latitude/longitude.
        return Station(
            id=str(item.get("CdStationHydro") or item["CdEntVigiCru"]),
            name=item.get("LbStationHydro") or item.get("LbEntVigiCru", ""),
            cours_eau=item.get("NomEntiteHydrographique") or item.get("LbCoursEau"),
            latitude=coord.get("Y"),
            longitude=coord.get("X"),
            troncon_id=_identifier(
                item.get("CdTronVigiCru") or parent.get("CdEntVigiCruSuperieur")
            ),
            troncon_name=item.get("LbTronVigiCru")
            or parent.get("LbEntVigiCruSuperieur"),
        )

    async def get_station_details(self, station_id: str) -> Station | None:
        data = await self._request(
            ENDPOINT_STATIONS,
            {
                "CdEntVigiCru": station_id,
                "TypEntVigiCru": "7",
            },
        )
        for item in _items(data):
            if (
                str(item.get("CdStationHydro") or item.get("CdEntVigiCru"))
                == station_id
            ):
                return self._station(item)
        return None

    async def get_observations(
        self, station_id: str, grandeur: str = "H"
    ) -> list[Observation]:
        data = await self._request(
            ENDPOINT_OBSERVATIONS,
            {
                "CdStationHydro": station_id,
                "GrdSerie": grandeur,
                "FormatDate": "iso",
            },
        )
        if not isinstance(data, dict) or not isinstance(data.get("Serie"), dict):
            raise VigicruesAPIError("Invalid observation response")
        serie = data["Serie"]
        if (
            serie.get("CdStationHydro", station_id) != station_id
            or serie.get("GrdSerie", grandeur) != grandeur
        ):
            raise VigicruesAPIError("Observation station or quantity mismatch")
        items = serie.get("ObssHydro")
        return self._observations(items, grandeur)

    @staticmethod
    def _observations(
        items: Any, grandeur: str, *, hubeau: bool = False
    ) -> list[Observation]:
        if not isinstance(items, list):
            raise VigicruesAPIError("Invalid observation list")
        observations = {}
        now = datetime.now(UTC)
        for item in items:
            try:
                timestamp = parse_datetime(
                    item.get("date_obs" if hubeau else "DtObsHydro")
                )
                if timestamp > now + timedelta(minutes=5):
                    continue
                value = finite_float(
                    item.get("resultat_obs" if hubeau else "ResObsHydro")
                )
                observations[timestamp] = Observation(
                    value=value / 1000 if hubeau else value,
                    timestamp=timestamp,
                    unit="m" if grandeur == "H" else "m³/s",
                    source="hubeau" if hubeau else "vigicrues",
                )
            except (ValueError, TypeError, AttributeError):
                _LOGGER.debug("Ignoring malformed observation")
        if items and not observations:
            raise VigicruesAPIError("No valid observations in response")
        return sorted(observations.values(), key=lambda obs: obs.timestamp)

    async def get_hubeau_observations(
        self, station_id: str, grandeur: str
    ) -> list[Observation]:
        data = await self._request(
            ENDPOINT_HUBEAU_OBSERVATIONS,
            {
                "code_entite": station_id,
                "grandeur_hydro": grandeur,
                "size": 5,
                "sort": "desc",
                "fields": "code_station,grandeur_hydro,date_obs,resultat_obs",
            },
        )
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise VigicruesAPIError("Invalid Hub'Eau response")
        # Never silently substitute a neighbouring station or another quantity.
        items = [
            x
            for x in data["data"]
            if isinstance(x, dict)
            and x.get("code_station") == station_id
            and x.get("grandeur_hydro") == grandeur
        ]
        if data["data"] and not items:
            raise VigicruesAPIError("Hub'Eau station or quantity mismatch")
        return self._observations(items, grandeur, hubeau=True)

    async def _observations_with_fallback(
        self, station_id: str, grandeur: str
    ) -> list[Observation]:
        primary: list[Observation] = []
        try:
            primary = await self.get_observations(station_id, grandeur)
            if primary and datetime.now(UTC) - primary[-1].timestamp <= STALE_AFTER:
                return primary
        except VigicruesAPIError as err:
            _LOGGER.debug("Vigicrues observations failed: %s", err)
        try:
            backup = await self.get_hubeau_observations(station_id, grandeur)
            if backup and (not primary or backup[-1].timestamp > primary[-1].timestamp):
                return backup
        except VigicruesAPIError:
            if not primary:
                raise
        if primary:
            return primary
        raise VigicruesAPIError("No observations from Vigicrues or Hub'Eau")

    async def get_previsions(
        self, station_id: str, grandeur: str = "H"
    ) -> list[Prevision]:
        data = await self._request(
            ENDPOINT_PREVISIONS,
            {
                "CdEntVigiCru": station_id,
                "TypEntVigiCru": "7",
                "GrdSimul": grandeur,
                "FormatDate": "iso",
            },
        )
        if not isinstance(data, dict) or not isinstance(data.get("Simul"), dict):
            raise VigicruesAPIError("Invalid forecast response")
        simulation = data["Simul"]
        if (
            simulation.get("CdEntVigiCru", station_id) != station_id
            or simulation.get("GrdSimul", grandeur) != grandeur
        ):
            raise VigicruesAPIError("Forecast station or quantity mismatch")
        items = simulation.get("Prevs")
        if not isinstance(items, list):
            raise VigicruesAPIError("Invalid forecast list")
        result = {}
        valid_count = 0
        now = datetime.now(UTC)
        for item in items:
            try:
                forecast = Prevision(
                    value=finite_float(item.get("ResMoyPrev")),
                    timestamp=parse_datetime(item.get("DtPrev")),
                    unit="m" if grandeur == "H" else "m³/s",
                    min_value=finite_float(item["ResMinPrev"])
                    if item.get("ResMinPrev") is not None
                    else None,
                    max_value=finite_float(item["ResMaxPrev"])
                    if item.get("ResMaxPrev") is not None
                    else None,
                )
                valid_count += 1
                if forecast.timestamp > now:
                    result[forecast.timestamp] = forecast
            except (ValueError, TypeError, AttributeError):
                _LOGGER.debug("Ignoring malformed forecast")
        if items and not valid_count:
            raise VigicruesAPIError("No valid forecasts in response")
        return sorted(result.values(), key=lambda forecast: forecast.timestamp)

    async def get_vigilance_levels(self) -> dict[str, str]:
        data = await self._request(ENDPOINT_VIGILANCE)
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise VigicruesAPIError("Invalid vigilance response")
        levels = {}
        for feature in data["features"]:
            if not isinstance(feature, dict) or not isinstance(
                feature.get("properties"), dict
            ):
                continue
            try:
                props = feature["properties"]
                section = props.get("CdEntCru") or props.get("CdEntVigiCru")
                level = int(props.get("NivInfViCr", props.get("NivSituVigiCruEnt")))
                if section and level in VIGILANCE_LEVELS:
                    levels[str(section)] = VIGILANCE_LEVELS[level]
            except (TypeError, ValueError, KeyError):
                continue
        if not levels:
            raise VigicruesAPIError("No valid vigilance levels")
        return levels

    async def get_station_data(self, station: Station) -> StationData:
        tasks = {
            "hauteur": self._observations_with_fallback(station.id, "H"),
            "debit": self._observations_with_fallback(station.id, "Q"),
            "hauteur_previsions": self.get_previsions(station.id, "H"),
            "debit_previsions": self.get_previsions(station.id, "Q"),
        }
        if station.troncon_id:
            tasks["vigilance"] = self.get_vigilance_levels()
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        now = datetime.now(UTC)
        data = StationData(station=station, last_attempt=now)
        for resource, result in zip(tasks, results, strict=True):
            if isinstance(result, VigicruesAPIError):
                data.errors[resource] = str(result)
                continue
            if isinstance(result, BaseException):
                raise result
            if resource == "vigilance":
                level = result.get(station.troncon_id)
                if level is None:
                    data.errors[resource] = "Section missing from vigilance feed"
                    continue
                data.vigilance_level = level
            elif resource in ("hauteur", "debit"):
                setattr(data, resource, result[-1] if result else None)
                setattr(data, f"tendance_{resource}", self._calculate_tendance(result))
            else:
                setattr(data, resource, result)
            data.last_success[resource] = now
        return data

    @staticmethod
    def _calculate_tendance(
        observations: list[Observation], sample_size: int = 5
    ) -> str | None:
        if len(observations) < 2:
            return None
        recent = sorted(observations, key=lambda obs: obs.timestamp)[-sample_size:]
        diff = recent[-1].value - recent[0].value
        threshold = max(abs(recent[0].value) * 0.01, 0.01)
        return (
            "hausse"
            if diff > threshold
            else "baisse"
            if diff < -threshold
            else "stable"
        )
