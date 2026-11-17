"""Constantes de l'intégration Letec Finder."""

import re

from homeassistant.const import Platform

DOMAIN = "letecfinder"
PLATFORMS = [Platform.DEVICE_TRACKER, Platform.SENSOR]

API_BASE = "https://letecfinder.be/map/api"
API_ITINERAIRE = "https://letecfinder.be/map/assets/api/itineraire.php"
DEFAULT_TOKEN = "token1"
DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MAX_SCAN_INTERVAL = 900

CONF_REGIONS = "regions"
CONF_LINES = "lines"
CONF_STOP_IDS = "stop_ids"
CONF_STOP_QUERIES = "stop_queries"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_API_TOKEN = "api_token"
CONF_INCLUDE_ALERTS = "include_alerts"
CONF_ALERTS_MODE = "alerts_mode"
CONF_ENRICH_BUSES = "enrich_buses"

REGIONS = {
    "L": "Liège - Verviers",
    "N": "Namur",
    "X": "Luxembourg",
    "H": "Hainaut",
    "C": "Charleroi",
    "B": "Brabant wallon",
}

ALERTS_MODES = {
    "all": "Toutes les alertes",
    "regions": "Alertes des régions suivies",
    "stops": "Alertes des arrêts suivis",
}

DEFAULT_REGIONS = ["L"]
DEFAULT_LINES = []
DEFAULT_STOP_IDS = ""
DEFAULT_STOP_QUERIES = ""
DEFAULT_INCLUDE_ALERTS = True
DEFAULT_ALERTS_MODE = "all"
DEFAULT_ENRICH_BUSES = False

MAX_BUS_DETAILS = 30


def parse_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = re.split(r"[,\n;]+", str(value))
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def normalize_line(value: str | int | None) -> str:
    return re.sub(r"^[A-Z]+", "", str(value or "").strip().upper()).strip()
