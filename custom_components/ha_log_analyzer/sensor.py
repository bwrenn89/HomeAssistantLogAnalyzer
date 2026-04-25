"""Sensor platform for HA Log Analyzer."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HALogAnalyzerCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HALogAnalyzerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([UnresolvedIssuesSensor(coordinator, entry.entry_id)], False)


class UnresolvedIssuesSensor(CoordinatorEntity, SensorEntity):
    """Tracks unresolved issue count from analyzed Home Assistant logs."""

    _attr_name = "HA Log Analyzer Unresolved Issues"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: HALogAnalyzerCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_unresolved_issues"

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("open_count", 0))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        issues = data.get("issues", {})
        return {
            "last_run": data.get("last_run"),
            "last_error": data.get("last_error"),
            "created_in_last_run": data.get("created", 0),
            "updated_in_last_run": data.get("updated", 0),
            "open_issue_fingerprints": [
                row.get("fingerprint")
                for row in issues.values()
                if row.get("status", "open") == "open"
            ],
            "issues": list(issues.values()),
        }
