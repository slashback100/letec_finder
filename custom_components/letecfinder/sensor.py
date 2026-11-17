"""Capteurs Letec Finder."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_INCLUDE_ALERTS,
    CONF_STOP_IDS,
    DEFAULT_INCLUDE_ALERTS,
    DOMAIN,
    parse_csv,
)
from .coordinator import LetecFinderCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LetecFinderCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [LetecFinderBusesSensor(coordinator, entry.entry_id)]
    if entry.data.get(CONF_INCLUDE_ALERTS, DEFAULT_INCLUDE_ALERTS):
        entities.append(LetecFinderAlertsSensor(coordinator, entry.entry_id))
    entities.append(LetecFinderRoutesSensor(coordinator, entry.entry_id))
    entities.extend(
        LetecFinderStopSensor(coordinator, entry.entry_id, stop_id)
        for stop_id in parse_csv(entry.data.get(CONF_STOP_IDS))
    )
    async_add_entities(entities)


class LetecFinderBaseSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LetecFinderCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Letec Finder",
            manufacturer="Letec Finder",
            configuration_url="https://letecfinder.be",
        )


class LetecFinderBusesSensor(LetecFinderBaseSensor):
    _attr_icon = "mdi:bus-clock"

    def __init__(self, coordinator: LetecFinderCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_buses"
        self._attr_name = "Bus suivis"
        self._attr_native_unit_of_measurement = "bus"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("buses", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {
            "buses": self.coordinator.data.get("buses", []),
            "agencies": self.coordinator.data.get("agencies", []),
            "lines": self.coordinator.data.get("lines", []),
        }


class LetecFinderAlertsSensor(LetecFinderBaseSensor):
    _attr_icon = "mdi:alert-outline"

    def __init__(self, coordinator: LetecFinderCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_alerts"
        self._attr_name = "Alertes réseau"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("alerts", {}).get("reports", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        alerts = self.coordinator.data.get("alerts", {})
        reports = alerts.get("reports", [])
        counts: dict[str, int] = {}
        for report in reports:
            category = str(report.get("category") or "autre")
            counts[category] = counts.get(category, 0) + 1
        return {
            "reports": reports,
            "zones": alerts.get("zones", []),
            "reports_by_category": counts,
        }


class LetecFinderRoutesSensor(LetecFinderBaseSensor):
    _attr_icon = "mdi:map-marker-path"

    def __init__(self, coordinator: LetecFinderCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self._attr_unique_id = f"{entry_id}_routes"
        self._attr_name = "Itinéraires"
        self._attr_native_unit_of_measurement = "tracé"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return len(self.coordinator.data.get("routes", {}).get("features", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {"geojson": self.coordinator.data.get("routes", {})}


class LetecFinderStopSensor(LetecFinderBaseSensor):
    _attr_icon = "mdi:bus-stop"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(
        self, coordinator: LetecFinderCoordinator, entry_id: str, stop_id: str
    ) -> None:
        super().__init__(coordinator, entry_id)
        self._stop_id = stop_id
        self._attr_unique_id = f"{entry_id}_stop_{stop_id}"

    @property
    def name(self) -> str:
        detail = self._stop_detail()
        return str(detail.get("stop_name") or self._stop_id)

    def _stop_detail(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("stops", {}).get(self._stop_id, {}).get("detail", {})

    @property
    def available(self) -> bool:
        return super().available and bool(
            self.coordinator.data
            and self._stop_id in self.coordinator.data.get("stops", {})
        )

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        departures = (
            self.coordinator.data.get("stops", {})
            .get(self._stop_id, {})
            .get("departures", [])
        )
        if not departures:
            return None
        minutes = departures[0].get("in_minutes")
        return int(minutes) if minutes is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        stop = self.coordinator.data.get("stops", {}).get(self._stop_id, {})
        detail = stop.get("detail", {})
        departures = stop.get("departures", [])
        next_departure = departures[0] if departures else {}
        return {
            "stop_id": self._stop_id,
            "stop_name": detail.get("stop_name"),
            "latitude": detail.get("stop_lat"),
            "longitude": detail.get("stop_lon"),
            "filter_routes": detail.get("filter_routes", []),
            "next_line": next_departure.get("line"),
            "next_destination": next_departure.get("destination"),
            "next_departure_time": next_departure.get("departure_time"),
            "next_trip_id": next_departure.get("trip_id"),
            "departures": departures,
        }
