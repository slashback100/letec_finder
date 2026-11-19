"""Coordinateur de données Letec Finder."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LetecFinderApiClient, LetecFinderError
from .const import (
    CONF_ALERTS_MODE,
    CONF_ENRICH_BUSES,
    CONF_INCLUDE_ALERTS,
    CONF_LINES,
    CONF_REGIONS,
    CONF_SCAN_INTERVAL,
    CONF_STOP_IDS,
    DEFAULT_SCAN_INTERVAL,
    MAX_BUS_DETAILS,
    normalize_line,
    parse_csv,
)
from .geojson import paths_to_geojson

_LOGGER = logging.getLogger(__name__)


class LetecFinderCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, client: LetecFinderApiClient, entry: ConfigEntry
    ) -> None:
        self.client = client
        self.config_entry = entry
        self._stop_details: dict[str, dict[str, Any]] = {}
        self._routes: dict[tuple[str, int], dict[str, Any]] = {}
        super().__init__(
            hass,
            _LOGGER,
            name="Letec Finder",
            update_interval=timedelta(
                seconds=entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            config_entry=entry,
        )

    def _line_match(self, route: str | None, selected: set[str]) -> bool:
        if not selected:
            return True
        return normalize_line(route) in selected

    def _filter_reports(self, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mode = self.config_entry.data.get(CONF_ALERTS_MODE, "all")
        if mode == "all":
            return reports
        regions = {str(region).upper() for region in parse_csv(self.config_entry.data.get(CONF_REGIONS))}
        if mode == "regions":
            return [r for r in reports if str(r.get("stop_id") or "")[:1].upper() in regions]
        stops = set(parse_csv(self.config_entry.data.get(CONF_STOP_IDS)))
        return [r for r in reports if r.get("stop_id") in stops]

    async def _async_update_data(self) -> dict[str, Any]:
        data = self.config_entry.data
        agencies = parse_csv(data.get(CONF_REGIONS))
        stop_ids = parse_csv(data.get(CONF_STOP_IDS))
        include_alerts = data.get(CONF_INCLUDE_ALERTS, True)
        enrich = data.get(CONF_ENRICH_BUSES, False)
        selected_lines = {normalize_line(line) for line in parse_csv(data.get(CONF_LINES))}

        tasks: dict[str, Any] = {
            "positions": self.client.async_get_positions(agencies),
            "schedules": asyncio.gather(
                *(self.client.async_get_stop_schedule(stop) for stop in stop_ids),
                return_exceptions=True,
            ),
        }
        if include_alerts:
            tasks["reports"] = self.client.async_get_reports()
        missing_details = [stop for stop in stop_ids if stop not in self._stop_details]
        if missing_details:
            tasks["details"] = asyncio.gather(
                *(self.client.async_get_stop_detail(stop) for stop in missing_details),
                return_exceptions=True,
            )

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        raw = dict(zip(tasks, results))

        if isinstance(raw.get("positions"), Exception):
            raise UpdateFailed(f"Impossible de récupérer les positions : {raw['positions']}")

        positions = raw["positions"] if isinstance(raw.get("positions"), list) else []
        buses = [
            dict(bus)
            for bus in positions
            if isinstance(bus, dict)
            and bus.get("vehicleId") is not None
            and self._line_match(bus.get("route_short_name"), selected_lines)
        ]
        buses.sort(key=lambda bus: str(bus.get("route_short_name") or ""))

        stop_data: dict[str, dict[str, Any]] = {}
        for stop_id, schedule in zip(stop_ids, raw.get("schedules") or []):
            if isinstance(schedule, Exception):
                _LOGGER.debug("Horaires indisponibles pour %s : %s", stop_id, schedule)
                schedule = {}
            departures = [
                dict(departure)
                for departure in (schedule.get("departures") or [])
                if isinstance(departure, dict)
                and self._line_match(departure.get("line"), selected_lines)
            ]
            stop_data[stop_id] = {
                "detail": self._stop_details.get(stop_id, {}),
                "schedule": schedule,
                "departures": departures,
            }

        details_result = raw.get("details")
        if details_result:
            for stop_id, detail in zip(missing_details, details_result):
                if isinstance(detail, dict):
                    self._stop_details[stop_id] = detail
                    if stop_id in stop_data:
                        stop_data[stop_id]["detail"] = detail
                else:
                    _LOGGER.debug("Détail indisponible pour %s : %s", stop_id, detail)

        reports_payload = raw.get("reports")
        alerts: dict[str, Any] = {"reports": [], "zones": []}
        if isinstance(reports_payload, dict):
            alerts = {
                "reports": self._filter_reports(list(reports_payload.get("reports") or [])),
                "zones": list(reports_payload.get("zones") or []),
            }
        elif isinstance(reports_payload, Exception):
            _LOGGER.debug("Alertes indisponibles : %s", reports_payload)

        routes: dict[str, Any] = {"type": "FeatureCollection", "features": []}
        if enrich and buses:
            enriched = buses[:MAX_BUS_DETAILS]
            bus_details = await self.client.async_get_buses(
                [str(bus["vehicleId"]) for bus in enriched]
            )
            for bus in enriched:
                detail = bus_details.get(str(bus["vehicleId"]))
                if detail:
                    bus.update(detail)

            trip_buses = [bus for bus in enriched if bus.get("tripId")]
            trip_infos = await asyncio.gather(
                *(
                    self.client.async_get_trip(str(bus["tripId"]))
                    for bus in trip_buses
                ),
                return_exceptions=True,
            )
            active_routes: set[tuple[str, int]] = set()
            for bus, trip in zip(trip_buses, trip_infos):
                if not isinstance(trip, dict):
                    _LOGGER.debug("Direction indisponible pour %s : %s", bus["tripId"], trip)
                    continue
                line = (
                    f"{bus.get('route_short_name') or ''} "
                    f"{bus.get('route_long_name') or ''}"
                ).strip()
                direction = trip.get("direction")
                try:
                    key = (line, int(direction))
                except (TypeError, ValueError):
                    continue
                active_routes.add(key)
                if key not in self._routes:
                    try:
                        paths = await self.client.async_get_itinerary(line, key[1])
                    except LetecFinderError as err:
                        _LOGGER.debug("Tracé indisponible pour %s : %s", line, err)
                        continue
                    self._routes[key] = paths_to_geojson(
                        paths,
                        {"line": line, "direction": key[1]},
                    )
            routes["features"] = [
                feature
                for key, route in self._routes.items()
                if key in active_routes
                for feature in route["features"]
            ]

        return {
            "buses": buses,
            "stops": stop_data,
            "alerts": alerts,
            "routes": routes,
            "agencies": agencies,
            "lines": parse_csv(data.get(CONF_LINES)),
        }
