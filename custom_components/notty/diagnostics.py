"""Provide diagnostics without credentials, identifiers, or response values."""

from __future__ import annotations

from typing import cast

from homeassistant.core import HomeAssistant

from custom_components.notty.api import JsonValue
from custom_components.notty.datapoints import inventory
from custom_components.notty.models import DeviceData, NottyConfigEntry


async def async_get_config_entry_diagnostics(_hass: HomeAssistant, entry: NottyConfigEntry) -> DeviceData:  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    """Only expose payload shapes, not account, pet or device values.

    Returns:
        The computed result.
    """
    coordinator = entry.runtime_data
    return {
        "last_update_success": coordinator.last_update_success,
        "device_count": len(coordinator.data or {}),
        "datapoints": cast("DeviceData", inventory(cast("list[JsonValue]", list((coordinator.data or {}).values())))),
    }
