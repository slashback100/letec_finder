"""Client asynchrone pour les API Letec Finder."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_BASE, DEFAULT_TOKEN

_LOGGER = logging.getLogger(__name__)


class LetecFinderError(Exception):
    pass


class LetecFinderAuthError(LetecFinderError):
    pass


class LetecFinderApiClient:
    def __init__(self, session: aiohttp.ClientSession, token: str = DEFAULT_TOKEN) -> None:
        self._session = session
        self._token = token or DEFAULT_TOKEN

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{API_BASE}/{path.lstrip('/')}"
        try:
            async with self._session.get(
                url, params=params, headers=self.headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status in (401, 403):
                    raise LetecFinderAuthError(f"Accès refusé par {url}")
                if response.status != 200:
                    raise LetecFinderError(f"HTTP {response.status} pour {url}")
                return await response.json(content_type=None)
        except (LetecFinderAuthError, LetecFinderError):
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise LetecFinderError(f"Appel API impossible ({url}) : {err}") from err

    async def async_get_positions(self, agencies: list[str], line: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"agency": ",".join(agencies)} if agencies else {}
        if line:
            params["route_short_name"] = line
        data = await self._get("bus/position", params)
        return list(data.get("position") or []) if isinstance(data, dict) else []

    async def async_get_lines(self, agencies: list[str]) -> list[dict[str, Any]]:
        params = {"agency": ",".join(agencies)} if agencies else {}
        data = await self._get("bus/lines", params)
        return list(data.get("lines") or []) if isinstance(data, dict) else []

    async def async_get_bus(self, vehicle_id: str) -> dict[str, Any] | None:
        data = await self._get("bus", {"vehicleId": str(vehicle_id)})
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    async def async_get_reports(self) -> dict[str, Any]:
        data = await self._get("reports.php")
        if not isinstance(data, dict):
            raise LetecFinderError("Réponse reports.php inattendue")
        return data

    async def async_search_stops(self, query: str) -> list[dict[str, Any]]:
        data = await self._get("arrets/search.php", {"q": query})
        if not isinstance(data, list):
            raise LetecFinderError("Réponse arrets/search inattendue")
        return [row for row in data if isinstance(row, dict)]

    async def async_get_stop_detail(self, stop_id: str) -> dict[str, Any]:
        data = await self._get("stopdetail.php", {"stopId": stop_id})
        if not isinstance(data, dict):
            raise LetecFinderError(f"Réponse stopdetail inattendue pour {stop_id}")
        return data

    async def async_get_stop_schedule(self, stop_id: str) -> dict[str, Any]:
        data = await self._get("stop-schedule.php", {"stopId": stop_id})
        if not isinstance(data, dict):
            raise LetecFinderError(f"Réponse stop-schedule inattendue pour {stop_id}")
        return data

    async def async_get_trip_schedule(self, trip_id: str) -> list[dict[str, Any]]:
        data = await self._get("horaire/schedule", {"trip_id": trip_id})
        if not isinstance(data, dict):
            raise LetecFinderError("Réponse horaire/schedule inattendue")
        return list(data.get("schedule") or [])

    async def async_get_buses(self, vehicle_ids: list[str]) -> dict[str, dict[str, Any]]:
        results = await asyncio.gather(
            *(self.async_get_bus(vehicle_id) for vehicle_id in vehicle_ids),
            return_exceptions=True,
        )
        details: dict[str, dict[str, Any]] = {}
        for vehicle_id, result in zip(vehicle_ids, results):
            if isinstance(result, dict):
                details[str(vehicle_id)] = result
            elif isinstance(result, Exception):
                _LOGGER.debug("Détail indisponible pour le bus %s : %s", vehicle_id, result)
        return details
