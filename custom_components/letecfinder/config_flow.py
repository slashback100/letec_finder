"""Configuration de l'intégration Letec Finder."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .api import LetecFinderApiClient, LetecFinderAuthError, LetecFinderError
from .const import (
    ALERTS_MODES,
    CONF_ALERTS_MODE,
    CONF_API_TOKEN,
    CONF_ENRICH_BUSES,
    CONF_INCLUDE_ALERTS,
    CONF_LINES,
    CONF_REGIONS,
    CONF_SCAN_INTERVAL,
    CONF_STOP_IDS,
    CONF_STOP_QUERIES,
    DEFAULT_ALERTS_MODE,
    DEFAULT_ENRICH_BUSES,
    DEFAULT_INCLUDE_ALERTS,
    DEFAULT_REGIONS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TOKEN,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    REGIONS,
    parse_csv,
)

_LOGGER = logging.getLogger(__name__)


def _region_options() -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=key, label=f"{key} — {label}") for key, label in REGIONS.items()
    ]


def _alerts_mode_options() -> list[SelectOptionDict]:
    return [
        SelectOptionDict(value=key, label=label) for key, label in ALERTS_MODES.items()
    ]


def _base_schema(regions: list[str], interval: int) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_REGIONS, default=regions): SelectSelector(
                SelectSelectorConfig(options=_region_options(), multiple=True)
            ),
            vol.Required(CONF_SCAN_INTERVAL, default=interval): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
        }
    )


def _lines_schema(selected: list[str], options: list[SelectOptionDict]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_LINES, default=selected): SelectSelector(
                SelectSelectorConfig(options=options, multiple=True, custom_value=True)
            ),
        }
    )


def _parse_queries(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = re.split(r"[\n;]+", str(value))
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def _stops_schema(
    queries: str, include_alerts: bool, alerts_mode: str, enrich: bool
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_STOP_QUERIES, default=queries): TextSelector(
                TextSelectorConfig()
            ),
            vol.Required(CONF_INCLUDE_ALERTS, default=include_alerts): BooleanSelector(),
            vol.Required(CONF_ALERTS_MODE, default=alerts_mode): SelectSelector(
                SelectSelectorConfig(options=_alerts_mode_options())
            ),
            vol.Required(CONF_ENRICH_BUSES, default=enrich): BooleanSelector(),
        }
    )


def _stops_select_schema(
    options: list[SelectOptionDict], default: list[str]
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_STOP_IDS, default=default): SelectSelector(
                SelectSelectorConfig(options=options, multiple=True, custom_value=True)
            ),
        }
    )


def _stop_options(
    results: list[dict[str, Any]], extra_ids: list[str]
) -> list[SelectOptionDict]:
    options: list[SelectOptionDict] = []
    seen: set[str] = set()
    for row in results:
        stop_id = str(row.get("stop_id") or "").strip()
        if not stop_id or stop_id in seen:
            continue
        seen.add(stop_id)
        label = str(row.get("stop_name") or stop_id)
        buses = ", ".join(str(bus) for bus in (row.get("buses") or [])[:6])
        options.append(
            SelectOptionDict(
                value=stop_id,
                label=f"{label} ({stop_id}) — {buses}" if buses else f"{label} ({stop_id})",
            )
        )
    for stop_id in extra_ids:
        if stop_id not in seen:
            options.append(
                SelectOptionDict(value=stop_id, label=f"{stop_id} (sélection précédente)")
            )
    return options


async def _validate_token(hass: Any, token: str, regions: list[str]) -> str | None:
    client = LetecFinderApiClient(async_get_clientsession(hass), token)
    try:
        await client.async_get_positions(regions)
    except LetecFinderAuthError:
        return "invalid_auth"
    except LetecFinderError as err:
        _LOGGER.debug("Validation du token impossible : %s", err)
        return "cannot_connect"
    return None


async def _line_options(hass: Any, token: str, regions: list[str]) -> list[SelectOptionDict]:
    client = LetecFinderApiClient(async_get_clientsession(hass), token)
    try:
        lines = await client.async_get_lines(regions)
    except LetecFinderError as err:
        _LOGGER.debug("Liste des lignes indisponible : %s", err)
        lines = []

    by_short: dict[str, str] = {}
    for line in lines:
        short = str(line.get("route_short_name") or "").strip()
        if not short:
            continue
        long_name = str(line.get("route_long_name") or "").strip()
        if short not in by_short or (long_name and not by_short[short]):
            by_short[short] = long_name

    def sort_key(short: str) -> tuple[int, Any]:
        return (0, int(short), "") if short.isdigit() else (1, 0, short)

    return [
        SelectOptionDict(
            value=short,
            label=f"{short} — {by_short[short]}" if by_short[short] else short,
        )
        for short in sorted(by_short, key=sort_key)
    ]


async def _search_stops(
    hass: Any, token: str, queries: list[str], regions: list[str]
) -> tuple[list[dict[str, Any]], str | None]:
    client = LetecFinderApiClient(async_get_clientsession(hass), token)
    results = await asyncio.gather(
        *(client.async_search_stops(query) for query in queries),
        return_exceptions=True,
    )
    if any(isinstance(result, LetecFinderAuthError) for result in results):
        return [], "invalid_auth"
    if not any(isinstance(result, list) for result in results):
        return [], "cannot_connect"

    region_codes = {str(region).upper() for region in regions}
    stops: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, list):
            continue
        for row in result:
            stop_id = str(row.get("stop_id") or "").strip()
            if not stop_id or stop_id in stops:
                continue
            if region_codes and stop_id[:1].upper() not in region_codes:
                continue
            stops[stop_id] = row
    if not stops:
        return [], "no_stops_found"
    return list(stops.values()), None


async def _validate_stops(hass: Any, token: str, stop_ids: list[str]) -> str | None:
    if not stop_ids:
        return None
    client = LetecFinderApiClient(async_get_clientsession(hass), token)
    results = await asyncio.gather(
        *(client.async_get_stop_detail(stop) for stop in stop_ids),
        return_exceptions=True,
    )
    if any(isinstance(result, LetecFinderAuthError) for result in results):
        return "invalid_auth"
    if any(isinstance(result, LetecFinderError) for result in results):
        return "cannot_connect"
    if any(not isinstance(result, dict) or not result.get("stop_name") for result in results):
        return "invalid_stop"
    return None


class LetecFinderConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._search_results: list[dict[str, Any]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config.update(user_input)
            self._config.setdefault(CONF_API_TOKEN, DEFAULT_TOKEN)
            error = await _validate_token(
                self.hass,
                self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
                parse_csv(self._config.get(CONF_REGIONS)),
            )
            if error:
                errors["base"] = error
            else:
                return await self.async_step_lines()

        options = await _line_options(
            self.hass,
            self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
            parse_csv(self._config.get(CONF_REGIONS)) or DEFAULT_REGIONS,
        )
        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(
                parse_csv(self._config.get(CONF_REGIONS)) or DEFAULT_REGIONS,
                self._config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            errors=errors,
        )

    async def async_step_lines(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._config[CONF_LINES] = parse_csv(user_input.get(CONF_LINES))
            return await self.async_step_stops()

        options = await _line_options(
            self.hass,
            self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
            parse_csv(self._config.get(CONF_REGIONS)),
        )
        return self.async_show_form(
            step_id="lines",
            data_schema=_lines_schema(parse_csv(self._config.get(CONF_LINES)), options),
        )

    async def async_step_stops(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config.update(user_input)
            self._config.setdefault(CONF_STOP_IDS, [])
            queries = _parse_queries(user_input.get(CONF_STOP_QUERIES))
            self._config[CONF_STOP_QUERIES] = queries
            if queries:
                results, error = await _search_stops(
                    self.hass,
                    self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
                    queries,
                    parse_csv(self._config.get(CONF_REGIONS)),
                )
                if error:
                    errors["base"] = error
                else:
                    self._search_results = results
                    return await self.async_step_stop_select()
            else:
                return self.async_create_entry(title="Letec Finder", data=self._config)

        return self.async_show_form(
            step_id="stops",
            data_schema=_stops_schema(
                "\n".join(parse_csv(self._config.get(CONF_STOP_QUERIES))),
                self._config.get(CONF_INCLUDE_ALERTS, DEFAULT_INCLUDE_ALERTS),
                self._config.get(CONF_ALERTS_MODE, DEFAULT_ALERTS_MODE),
                self._config.get(CONF_ENRICH_BUSES, DEFAULT_ENRICH_BUSES),
            ),
            errors=errors,
        )

    async def async_step_stop_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        previous = parse_csv(self._config.get(CONF_STOP_IDS))
        found_ids = [str(row.get("stop_id")) for row in self._search_results]
        options = _stop_options(self._search_results, previous)
        if user_input is not None:
            selected = parse_csv(user_input.get(CONF_STOP_IDS))
            custom = [stop_id for stop_id in selected if stop_id not in found_ids]
            error = await _validate_stops(
                self.hass, self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN), custom
            )
            if error:
                errors["base"] = error
            else:
                self._config[CONF_STOP_IDS] = selected
                return self.async_create_entry(title="Letec Finder", data=self._config)

        common = [stop_id for stop_id in found_ids if stop_id in previous]
        default = common or found_ids
        return self.async_show_form(
            step_id="stop_select",
            data_schema=_stops_select_schema(options, default),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LetecFinderOptionsFlow(config_entry)


class LetecFinderOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config: dict[str, Any] = dict(config_entry.data)
        self._search_results: list[dict[str, Any]] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config.update(user_input)
            self._config.setdefault(CONF_API_TOKEN, DEFAULT_TOKEN)
            error = await _validate_token(
                self.hass,
                self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
                parse_csv(self._config.get(CONF_REGIONS)),
            )
            if error:
                errors["base"] = error
            else:
                return await self.async_step_lines()

        return self.async_show_form(
            step_id="init",
            data_schema=_base_schema(
                parse_csv(self._config.get(CONF_REGIONS)) or DEFAULT_REGIONS,
                self._config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ),
            errors=errors,
        )

    async def async_step_lines(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._config[CONF_LINES] = parse_csv(user_input.get(CONF_LINES))
            return await self.async_step_stops()

        options = await _line_options(
            self.hass,
            self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
            parse_csv(self._config.get(CONF_REGIONS)),
        )
        return self.async_show_form(
            step_id="lines",
            data_schema=_lines_schema(parse_csv(self._config.get(CONF_LINES)), options),
        )

    async def async_step_stops(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config.update(user_input)
            queries = _parse_queries(user_input.get(CONF_STOP_QUERIES))
            self._config[CONF_STOP_QUERIES] = queries
            if queries:
                results, error = await _search_stops(
                    self.hass,
                    self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
                    queries,
                    parse_csv(self._config.get(CONF_REGIONS)),
                )
                if error:
                    errors["base"] = error
                else:
                    self._search_results = results
                    return await self.async_step_stop_select()
            else:
                return self._save()

        return self.async_show_form(
            step_id="stops",
            data_schema=_stops_schema(
                "\n".join(parse_csv(self._config.get(CONF_STOP_QUERIES))),
                self._config.get(CONF_INCLUDE_ALERTS, DEFAULT_INCLUDE_ALERTS),
                self._config.get(CONF_ALERTS_MODE, DEFAULT_ALERTS_MODE),
                self._config.get(CONF_ENRICH_BUSES, DEFAULT_ENRICH_BUSES),
            ),
            errors=errors,
        )

    async def async_step_stop_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        previous = parse_csv(self._config.get(CONF_STOP_IDS))
        found_ids = [str(row.get("stop_id")) for row in self._search_results]
        options = _stop_options(self._search_results, previous)
        if user_input is not None:
            selected = parse_csv(user_input.get(CONF_STOP_IDS))
            custom = [stop_id for stop_id in selected if stop_id not in found_ids]
            error = await _validate_stops(
                self.hass, self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN), custom
            )
            if error:
                errors["base"] = error
            else:
                self._config[CONF_STOP_IDS] = selected
                return self._save()

        common = [stop_id for stop_id in found_ids if stop_id in previous]
        default = common or found_ids
        return self.async_show_form(
            step_id="stop_select",
            data_schema=_stops_select_schema(options, default),
            errors=errors,
        )

    def _save(self) -> FlowResult:
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self._config
        )
        return self.async_create_entry(title="", data={})
