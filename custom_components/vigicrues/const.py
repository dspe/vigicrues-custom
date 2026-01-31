"""Constants for the Vigicrues integration."""

from datetime import timedelta
from typing import Final

# Domain
DOMAIN: Final = "vigicrues"

# API Base URL
API_BASE_URL: Final = "https://www.vigicrues.gouv.fr/services"
API_VERSION: Final = "v1.1"

# API Endpoints
ENDPOINT_TERRITORIES: Final = f"{API_BASE_URL}/{API_VERSION}/TerEntVigiCru.json"
ENDPOINT_TRONCONS: Final = f"{API_BASE_URL}/{API_VERSION}/TronEntVigiCru.json"
ENDPOINT_STATIONS: Final = f"{API_BASE_URL}/{API_VERSION}/StaEntVigiCru.json"
ENDPOINT_PREVISIONS: Final = f"{API_BASE_URL}/{API_VERSION}/prevision.json"
ENDPOINT_OBSERVATIONS: Final = f"{API_BASE_URL}/observations.json"
ENDPOINT_VIGILANCE: Final = f"{API_BASE_URL}/1/InfoVigiCru.geojson"

# Update intervals
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=15)
VIGILANCE_SCAN_INTERVAL: Final = timedelta(hours=1)
MIN_SCAN_INTERVAL: Final = timedelta(minutes=5)

# Configuration keys
CONF_STATION_ID: Final = "station_id"
CONF_STATION_NAME: Final = "station_name"
CONF_TERRITORY_ID: Final = "territory_id"
CONF_TERRITORY_NAME: Final = "territory_name"
CONF_TRONCON_ID: Final = "troncon_id"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Entity types
SENSOR_TYPE_HAUTEUR: Final = "hauteur"
SENSOR_TYPE_DEBIT: Final = "debit"
SENSOR_TYPE_VIGILANCE: Final = "vigilance"
SENSOR_TYPE_TENDANCE: Final = "tendance"

# Vigilance levels
VIGILANCE_VERT: Final = "Vert"
VIGILANCE_JAUNE: Final = "Jaune"
VIGILANCE_ORANGE: Final = "Orange"
VIGILANCE_ROUGE: Final = "Rouge"

VIGILANCE_LEVELS: Final = {
    1: VIGILANCE_VERT,
    2: VIGILANCE_JAUNE,
    3: VIGILANCE_ORANGE,
    4: VIGILANCE_ROUGE,
}

# Tendance
TENDANCE_STABLE: Final = "stable"
TENDANCE_HAUSSE: Final = "hausse"
TENDANCE_BAISSE: Final = "baisse"

# Units
UNIT_HAUTEUR: Final = "m"
UNIT_DEBIT: Final = "m³/s"

# Attributes
ATTR_STATION_ID: Final = "station_id"
ATTR_STATION_NAME: Final = "station_name"
ATTR_COURS_EAU: Final = "cours_eau"
ATTR_LATITUDE: Final = "latitude"
ATTR_LONGITUDE: Final = "longitude"
ATTR_TIMESTAMP: Final = "timestamp"
ATTR_PREVISIONS: Final = "previsions"
ATTR_CRUES_HISTORIQUES: Final = "crues_historiques"
ATTR_TRONCON: Final = "troncon"

# Platforms
PLATFORMS: Final = ["sensor"]
