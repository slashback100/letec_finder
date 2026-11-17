"""Configuration de l'intégration Letec Finder."""

from __future__ import annotations

import asyncio
import logging
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


def _base_schema(regions: list[str], interval: int, token: str) -> vol.Schema:
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
            vol.Required(CONF_API_TOKEN, default=token): TextSelector(
                TextSelectorConfig()
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


def _stops_schema(
    stop_ids: str, include_alerts: bool, alerts_mode: str, enrich: bool
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_STOP_IDS, default=stop_ids): TextSelector(TextSelectorConfig()),
            vol.Required(CONF_INCLUDE_ALERTS, default=include_alerts): BooleanSelector(),
            vol.Required(CONF_ALERTS_MODE, default=alerts_mode): SelectSelector(
                SelectSelectorConfig(options=_alerts_mode_options())
            ),
            vol.Required(CONF_ENRICH_BUSES, default=enrich): BooleanSelector(),
        }
    )


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
    if any(not isinstance(result, dict) or not result.get("stop_name") for result in results):
        return "invalid_stop"
    return None


class LetecFinderConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config.update(user_input)
            error = await _validate_token(
                self.hass,
                self._config[CONF_API_TOKEN],
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
                self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
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
            self._config[CONF_STOP_IDS] = parse_csv(user_input.get(CONF_STOP_IDS))
            error = await _validate_stops(
                self.hass,
                self._config[CONF_API_TOKEN],
                self._config[CONF_STOP_IDS],
            )
            if error:
                errors["base"] = error
                self._config[CONF_STOP_IDS] = user_input.get(CONF_STOP_IDS, "")
            else:
                return self.async_create_entry(title="Letec Finder", data=self._config)

        return self.async_show_form(
            step_id="stops",
            data_schema=_stops_schema(
                self._config.get(CONF_STOP_IDS, ""),
                self._config.get(CONF_INCLUDE_ALERTS, DEFAULT_INCLUDE_ALERTS),
                self._config.get(CONF_ALERTS_MODE, DEFAULT_ALERTS_MODE),
                self._config.get(CONF_ENRICH_BUSES, DEFAULT_ENRICH_BUSES),
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LetecFinderOptionsFlow(config_entry)


class LetecFinderOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config: dict[str, Any] = dict(config_entry.data)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config.update(user_input)
            error = await _validate_token(
                self.hass,
                self._config[CONF_API_TOKEN],
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
                self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN),
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
            stops = parse_csv(user_input.get(CONF_STOP_IDS))
            error = await _validate_stops(
                self.hass, self._config.get(CONF_API_TOKEN, DEFAULT_TOKEN), stops
            )
            if error:
                errors["base"] = error
            else:
                self._config[CONF_STOP_IDS] = stops
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=self._config
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="stops",
            data_schema=_stops_schema(
                ", ".join(parse_csv(self._config.get(CONF_STOP_IDS))),
                self._config.get(CONF_INCLUDE_ALERTS, DEFAULT_INCLUDE_ALERTS),
                self._config.get(CONF_ALERTS_MODE, DEFAULT_ALERTS_MODE),
                self._config.get(CONF_ENRICH_BUSES, DEFAULT_ENRICH_BUSES),
            ),
            errors=errors,
        )
