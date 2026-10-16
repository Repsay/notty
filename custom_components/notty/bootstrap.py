from __future__ import annotations

from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.notty.api import (
    REMINDER_CYCLE_FIELDS,
    REMINDER_LITTER_INTERVAL_ACTION,
    SAFE_LITTER_ACTIONS,
    JsonObject,
    NottyApi,
    NottyApiError,
    NottyAuthError,
    reminder_payload,
)
from custom_components.notty.const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_FIREBASE_API_KEY,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_REGION_CODE,
    CONF_USER_ID,
    CONF_VERIFICATION_CODE,
    CONFIG_ENTRY_VERSION,
    DEFAULT_REGION_CODE,
    DOMAIN,
    PLATFORMS,
)
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import value_from_block
from custom_components.notty.models import NottyConfigEntry
from custom_components.notty.validation import vol

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"

SERVICE_LITTER_BOX_ACTION = "litter_box_action"
SERVICE_LITTER_BOX_ONE_KEY = "litter_box_one_key"
SERVICE_DEVICE_FIELD = "user_device_id"
ONE_KEY_ACTIONS = {"clean": 0, "level": 1, "empty": 2, "sterilize": 3}


def _get_coordinator(hass: HomeAssistant, user_device_id: str) -> NottyCoordinator:
    for entry in cast("list[NottyConfigEntry]", hass.config_entries.async_entries(DOMAIN)):
        coordinator = cast("NottyCoordinator | None", getattr(entry, "runtime_data", None))
        if not isinstance(coordinator, NottyCoordinator):
            continue
        if user_device_id in coordinator.data:
            block = coordinator.data[user_device_id]
            if (
                block.get("type") != DEVICE_TYPE_LITTER_BOX
                or block.get("device", {}).get("_notty_source") == SOURCE_PET
            ):
                msg = "NOTTY actions require a physical litter box device ID"
                raise HomeAssistantError(msg)
            return coordinator
    msg = f"NOTTY device {user_device_id} was not found"
    raise HomeAssistantError(msg)


def _validate_litter_interval_change(coordinator: NottyCoordinator, device_id: str, data: JsonObject) -> None:
    """Reject untested reminder states and no-op cycle writes.

    Raises:
        NottyApiError: If the target is not an enabled reminder with a valid changing interval.
    """
    block = coordinator.data[device_id]
    enabled = value_from_block(block, "open_litter_remind")
    if not (enabled is True or (type(enabled) is int and enabled == 1) or (isinstance(enabled, str) and enabled in {"1", "true"})):
        msg = "Litter interval changes require an enabled reminder"
        raise NottyApiError(msg)
    current_cycle = value_from_block(block, "default_remaining_days")
    if isinstance(current_cycle, str) and current_cycle.isascii() and current_cycle.isdecimal():
        current_cycle = int(current_cycle)
    if type(current_cycle) is not int or current_cycle not in range(5, 31):
        msg = "Litter interval changes require a valid configured cycle"
        raise NottyApiError(msg)
    if data["cycle_time"] == current_cycle:
        msg = "Litter interval is unchanged; reset behavior remains unverified"
        raise NottyApiError(msg)


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LITTER_BOX_ACTION):
        return

    async def handle_litter_box_one_key(call: ServiceCall) -> None:
        """Handle litter box one key.

        Raises:
            HomeAssistantError: When the requested operation cannot be completed.
        """
        call_data = cast("JsonObject", call.data)
        user_device_id = str(call_data[SERVICE_DEVICE_FIELD])
        coordinator = _get_coordinator(hass, user_device_id)
        one_key = call_data["one_key"]
        if isinstance(one_key, str) and one_key in ONE_KEY_ACTIONS:
            one_key = ONE_KEY_ACTIONS[one_key]
        try:
            await coordinator.api.command(user_device_id, one_key, "litter_box")
        except NottyApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_litter_box_action(call: ServiceCall) -> None:
        """Handle litter box action.

        Raises:
            HomeAssistantError: When the requested operation cannot be completed.
        """
        call_data = cast("JsonObject", call.data)
        user_device_id = str(call_data[SERVICE_DEVICE_FIELD])
        coordinator = _get_coordinator(hass, user_device_id)
        action = str(call_data["action"])
        action_data = call_data.get("data")
        if not isinstance(action_data, dict):
            action_data = {}
        try:
            if action in REMINDER_CYCLE_FIELDS:
                action_data = reminder_payload(action, action_data)
                if action == REMINDER_LITTER_INTERVAL_ACTION:
                    _validate_litter_interval_change(coordinator, user_device_id, action_data)
            await coordinator.api.litter_action(user_device_id, action, action_data)
        except NottyApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    device_id_validator: vol.Coerce[str] = vol.Coerce(str)
    command_validator: vol.Coerce[int] = vol.Coerce(int)
    empty_data: JsonObject = {}
    one_key_schema: dict[object, object] = {
        vol.Required(SERVICE_DEVICE_FIELD): device_id_validator,
        vol.Required("one_key"): vol.Any(vol.In(ONE_KEY_ACTIONS), command_validator),
    }
    action_schema: dict[object, object] = {
        vol.Required(SERVICE_DEVICE_FIELD): device_id_validator,
        vol.Required("action"): vol.In(SAFE_LITTER_ACTIONS),
        vol.Optional("data", default=empty_data): cast("type[dict[str, object]]", dict),
    }
    hass.services.async_register(
        DOMAIN, SERVICE_LITTER_BOX_ONE_KEY, handle_litter_box_one_key, schema=vol.Schema(one_key_schema)
    )
    hass.services.async_register(
        DOMAIN, SERVICE_LITTER_BOX_ACTION, handle_litter_box_action, schema=vol.Schema(action_schema)
    )


async def async_setup_entry(hass: HomeAssistant, entry: NottyConfigEntry) -> bool:
    """Async setup entry.

    Returns:
        bool: The resulting async setup entry.

    Raises:
        ConfigEntryAuthFailed: When the requested operation cannot be completed.
        ConfigEntryNotReady: When the requested operation cannot be completed.
    """
    stored = cast("dict[str, str]", entry.data)
    api = NottyApi(
        async_get_clientsession(hass),
        email=stored.get(CONF_EMAIL),
        token=stored.get(CONF_ACCESS_TOKEN),
        refresh_token=stored.get(CONF_REFRESH_TOKEN),
        user_id=stored.get(CONF_USER_ID),
        region_code=stored.get(CONF_REGION_CODE, DEFAULT_REGION_CODE),
    )
    if not api.token:
        try:
            await api.login()
        except NottyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NottyApiError as err:
            raise ConfigEntryNotReady(str(err)) from err
    coordinator = NottyCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NottyConfigEntry) -> bool:
    """Async unload entry.

    Returns:
        bool: The resulting async unload entry.
    """
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not [
        loaded_entry
        for loaded_entry in cast("list[NottyConfigEntry]", hass.config_entries.async_entries(DOMAIN))
        if loaded_entry.entry_id != entry.entry_id
    ]:
        hass.services.async_remove(DOMAIN, SERVICE_LITTER_BOX_ONE_KEY)
        hass.services.async_remove(DOMAIN, SERVICE_LITTER_BOX_ACTION)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: NottyConfigEntry) -> bool:  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    """Keep accounts configured by earlier prototype releases usable.

    Returns:
        The computed result.
    """
    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version < CONFIG_ENTRY_VERSION:
        data = dict(cast("JsonObject", entry.data))
        for key in (CONF_PASSWORD, CONF_FIREBASE_API_KEY, CONF_VERIFICATION_CODE):
            data.pop(key, None)
        hass.config_entries.async_update_entry(entry, data=data, version=CONFIG_ENTRY_VERSION)
    return True
