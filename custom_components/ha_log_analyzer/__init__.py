"""HA Log Analyzer integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, PLATFORMS, SERVICE_REOPEN_ISSUE, SERVICE_RESOLVE_ISSUE, SERVICE_RUN_ANALYSIS
from .coordinator import HALogAnalyzerCoordinator

LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["logger"] = LOGGER
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HALogAnalyzerCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_refresh_interval()
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _handle_run_analysis(call: ServiceCall) -> None:
        del call
        await coordinator.async_run_analysis_now()

    async def _handle_resolve(call: ServiceCall) -> None:
        fingerprint = call.data["fingerprint"]
        ok = await coordinator.async_set_issue_status(fingerprint, "resolved")
        if not ok:
            raise HomeAssistantError("Issue fingerprint not found.")

    async def _handle_reopen(call: ServiceCall) -> None:
        fingerprint = call.data["fingerprint"]
        ok = await coordinator.async_set_issue_status(fingerprint, "open")
        if not ok:
            raise HomeAssistantError("Issue fingerprint not found.")

    if not hass.services.has_service(DOMAIN, SERVICE_RUN_ANALYSIS):
        hass.services.async_register(DOMAIN, SERVICE_RUN_ANALYSIS, _handle_run_analysis)
    if not hass.services.has_service(DOMAIN, SERVICE_RESOLVE_ISSUE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESOLVE_ISSUE,
            _handle_resolve,
            schema=vol.Schema({vol.Required("fingerprint"): str}),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REOPEN_ISSUE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REOPEN_ISSUE,
            _handle_reopen,
            schema=vol.Schema({vol.Required("fingerprint"): str}),
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_RUN_ANALYSIS)
        hass.services.async_remove(DOMAIN, SERVICE_RESOLVE_ISSUE)
        hass.services.async_remove(DOMAIN, SERVICE_REOPEN_ISSUE)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
