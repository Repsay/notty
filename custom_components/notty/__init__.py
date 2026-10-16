import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SAFE_LITTER_ACTIONS, NottyApi, NottyApiError, NottyAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_FIREBASE_API_KEY,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_REGION_CODE,
    CONF_USER_ID,
    CONF_VERIFICATION_CODE,
    DEFAULT_REGION_CODE,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import NottyCoordinator

SERVICE_LITTER_BOX_ACTION = "litter_box_action"
SERVICE_LITTER_BOX_ONE_KEY = "litter_box_one_key"
SERVICE_DEVICE_FIELD = "user_device_id"
ONE_KEY_ACTIONS = {"clean": 0, "level": 1, "empty": 2, "sterilize": 3}


async def _async_get_coordinator(hass: HomeAssistant, user_device_id: str) -> NottyCoordinator:
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if not isinstance(coordinator, NottyCoordinator):
            continue
        if user_device_id in coordinator.data:
            block = coordinator.data[user_device_id]
            if (
                block.get("type") != "litter_box"
                or block.get("device", {}).get("_notty_source") == "pet"
            ):
                raise HomeAssistantError("NOTTY actions require a physical litter box device ID")
            return coordinator
    raise HomeAssistantError(f"NOTTY device {user_device_id} was not found")


async def _async_register_services(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    async def handle_litter_box_one_key(call):
        user_device_id = call.data[SERVICE_DEVICE_FIELD]
        coordinator = await _async_get_coordinator(hass, user_device_id)
        one_key = call.data["one_key"]
        one_key = ONE_KEY_ACTIONS.get(one_key, one_key)
        try:
            await coordinator.api.command(user_device_id, one_key, "litter_box")
        except NottyApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    async def handle_litter_box_action(call):
        user_device_id = call.data[SERVICE_DEVICE_FIELD]
        coordinator = await _async_get_coordinator(hass, user_device_id)
        try:
            await coordinator.api.litter_action(
                user_device_id,
                call.data["action"],
                call.data.get("data") or {},
            )
        except NottyApiError as err:
            raise HomeAssistantError(str(err)) from err
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_LITTER_BOX_ONE_KEY,
        handle_litter_box_one_key,
        schema=vol.Schema(
            {
                vol.Required(SERVICE_DEVICE_FIELD): vol.Coerce(str),
                vol.Required("one_key"): vol.Any(
                    vol.In({"clean", "level", "empty", "sterilize"}),
                    vol.Coerce(int),
                ),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LITTER_BOX_ACTION,
        handle_litter_box_action,
        schema=vol.Schema(
            {
                vol.Required(SERVICE_DEVICE_FIELD): vol.Coerce(str),
                vol.Required("action"): vol.In(SAFE_LITTER_ACTIONS),
                vol.Optional("data", default={}): dict,
            }
        ),
    )
    domain_data["services_registered"] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = NottyApi(
        async_get_clientsession(hass),
        email=entry.data.get(CONF_EMAIL),
        password=entry.data.get(CONF_PASSWORD),
        verification_code=entry.data.get(CONF_VERIFICATION_CODE),
        token=entry.data.get(CONF_ACCESS_TOKEN),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        user_id=entry.data.get(CONF_USER_ID),
        firebase_api_key=entry.data.get(CONF_FIREBASE_API_KEY),
        region_code=entry.data.get(CONF_REGION_CODE, DEFAULT_REGION_CODE),
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
    await _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not [
        loaded_entry
        for loaded_entry in hass.config_entries.async_entries(DOMAIN)
        if loaded_entry.entry_id != entry.entry_id
    ]:
        hass.services.async_remove(DOMAIN, SERVICE_LITTER_BOX_ONE_KEY)
        hass.services.async_remove(DOMAIN, SERVICE_LITTER_BOX_ACTION)
        hass.data.get(DOMAIN, {}).pop("services_registered", None)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Keep accounts configured by earlier prototype releases usable."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
    return True
