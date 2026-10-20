"""JSON-safe snapshots for recovery after Home Assistant restarts."""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from .api import (
    Observation,
    Prevision,
    Station,
    StationData,
    finite_float,
    parse_datetime,
)


def serialize(data: StationData) -> dict[str, Any]:
    """Encode only integration-owned data for Home Assistant storage."""

    def encode(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    return encode(asdict(data))


def deserialize(payload: dict[str, Any], station_id: str) -> StationData:
    """Reject corrupt snapshots and snapshots belonging to another station."""
    station = Station(**payload["station"])
    if station.id != station_id:
        raise ValueError("Cached station mismatch")
    result = StationData(station=station)
    for resource in ("hauteur", "debit"):
        item = payload.get(resource)
        if item is not None:
            setattr(
                result,
                resource,
                Observation(
                    value=finite_float(item["value"]),
                    timestamp=parse_datetime(item["timestamp"]),
                    unit=item["unit"],
                    source=item.get("source", "vigicrues"),
                ),
            )
        setattr(result, f"tendance_{resource}", payload.get(f"tendance_{resource}"))
        forecasts = []
        for item in payload.get(f"{resource}_previsions") or []:
            forecasts.append(
                Prevision(
                    value=finite_float(item["value"]),
                    timestamp=parse_datetime(item["timestamp"]),
                    unit=item["unit"],
                    min_value=finite_float(item["min_value"])
                    if item.get("min_value") is not None
                    else None,
                    max_value=finite_float(item["max_value"])
                    if item.get("max_value") is not None
                    else None,
                )
            )
        setattr(result, f"{resource}_previsions", forecasts)
    result.vigilance_level = payload.get("vigilance_level")
    result.last_success = {
        key: parse_datetime(value)
        for key, value in payload.get("last_success", {}).items()
    }
    # A restored resource is stale until it has actually been refreshed.
    result.errors = {key: "Restored from local cache" for key in result.last_success}
    if payload.get("last_attempt"):
        result.last_attempt = parse_datetime(payload["last_attempt"])
    return result
