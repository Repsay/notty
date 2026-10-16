"""Provide diagnostics without credentials, identifiers, or response values."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .datapoints import inventory


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Only expose payload shapes, not account, pet or device values."""
    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "device_count": len(coordinator.data or {}),
        "datapoints": inventory(list((coordinator.data or {}).values())),
    }
