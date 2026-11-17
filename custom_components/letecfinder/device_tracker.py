"""Suivi des bus Letec Finder sur la carte."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LetecFinderCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: LetecFinderCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def add_new_buses() -> None:
        if not coordinator.data:
            return
        entities = []
        for bus in coordinator.data.get("buses", []):
            vehicle_id = str(bus.get("vehicleId") or "")
            if not vehicle_id or vehicle_id in known:
                continue
            known.add(vehicle_id)
            entities.append(LetecFinderBusTracker(coordinator, entry.entry_id, vehicle_id))
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(coordinator.async_add_listener(add_new_buses))
    add_new_buses()


class LetecFinderBusTracker(CoordinatorEntity, TrackerEntity):
    _attr_has_entity_name = True
    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:bus"
    _attr_location_accuracy = 50

    def __init__(
        self, coordinator: LetecFinderCoordinator, entry_id: str, vehicle_id: str
    ) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id
        self._lat = 0.0
        self._lng = 0.0
        self._line = ""
        self._attr_unique_id = f"{entry_id}_bus_{vehicle_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Letec Finder",
            manufacturer="Letec Finder",
            configuration_url="https://letecfinder.be",
        )
        self._sync()

    @property
    def _bus(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        for bus in self.coordinator.data.get("buses", []):
            if str(bus.get("vehicleId")) == self._vehicle_id:
                return bus
        return None

    def _sync(self) -> None:
        bus = self._bus
        if not bus:
            return
        line = str(bus.get("route_short_name") or "").strip()
        if line:
            self._line = line
        try:
            self._lat = float(bus.get("latitude"))
            self._lng = float(bus.get("longitude"))
        except (TypeError, ValueError):
            pass

    @property
    def name(self) -> str:
        if self._line:
            return f"Bus {self._line} ({self._vehicle_id})"
        return f"Bus {self._vehicle_id}"

    @property
    def available(self) -> bool:
        return super().available and self._bus is not None

    @property
    def latitude(self) -> float:
        return self._lat

    @property
    def longitude(self) -> float:
        return self._lng

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync()
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        bus = self._bus or {}
        return {
            "vehicle_id": self._vehicle_id,
            "line": bus.get("route_short_name"),
            "agency": bus.get("agency"),
            "bearing": bus.get("bearing"),
            "speed": bus.get("speed"),
            "trip_id": bus.get("tripId"),
            "route_long_name": bus.get("route_long_name"),
            "current_stop_sequence": bus.get("currentStopSequence"),
        }
