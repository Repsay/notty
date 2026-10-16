"""Configuration of the NOTTY cloud name without changing HA user overrides."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import MAX_ALIAS_UNITS, NottyApiError, alias_payload
from custom_components.notty.const import DOMAIN
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity
from custom_components.notty.models import DeviceBlock, DeviceData, NottyConfigEntry

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"
MAX_STATE_LENGTH = 255


def cloud_alias(block: DeviceBlock) -> str | None:
    """Read the discovery alias, falling back to info only when the field is absent.

    Returns:
        The exact reported name, or None for missing or invalid metadata.
    """
    value = block["device"].get("alias", block["info"].get("alias"))
    if not isinstance(value, str) or not value or len(value) > MAX_STATE_LENGTH or not value.isprintable():
        return None
    return value


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async platform setup callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Expose cloud-name configuration only for physical litter boxes."""
    coordinator = entry.runtime_data
    async_add_entities(
        NottyCloudAlias(coordinator, device_id, block["device"])
        for device_id, block in coordinator.data.items()
        if block["type"] == DEVICE_TYPE_LITTER_BOX and block["device"].get("_notty_source") != SOURCE_PET
    )


class NottyCloudAlias(NottyEntity, TextEntity):
    """An account-side alias with identity and HA naming kept separate."""

    _attr_name = "Cloud name"
    _attr_translation_key = "cloud_alias"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = TextMode.TEXT
    # HA measures code points, whereas Dart's String.length measures UTF-16 units.
    # One non-BMP character can satisfy the app's minimum of two units.
    _attr_native_min = 1

    def __init__(self, coordinator: NottyCoordinator, device_id: str, device: DeviceData) -> None:
        super().__init__(coordinator, device_id, device)
        self._attr_unique_id = f"{device_id}_cloud_alias"

    @property
    def native_value(self) -> str | None:
        """The reported cloud alias, independent of the HA registry display name.

        Returns:
            Current server readback without optimistic replacements.
        """
        return cloud_alias(self.block)

    @property
    def native_max(self) -> int:
        """The display bound also accommodates an existing longer server alias.

        Returns:
            Enough room to display legacy readback; new writes still use the API policy.
        """
        return max(MAX_ALIAS_UNITS, len(self.native_value or ""))

    @property
    def available(self) -> bool:
        """Whether the configured physical device has a usable cloud-name readback.

        Returns:
            True for current, known device metadata.
        """
        return super().available and self.native_value is not None

    def _handle_coordinator_update(self) -> None:
        name = self.native_value
        if self.available and name is not None and self.coordinator.entry_id is not None:
            registry = async_get_device_registry(self.hass)
            if hasattr(registry, "async_get_device_by_identifier"):
                device = registry.async_get_device_by_identifier((DOMAIN, self.device_id), self.coordinator.entry_id)
            else:
                device = registry.async_get_device(identifiers={(DOMAIN, self.device_id)})
            if device is not None and device.name != name:
                registry.async_update_device(device.id, name=name)
        super()._handle_coordinator_update()

    async def async_set_value(self, value: str) -> None:
        """Rename the cloud device, then refresh authoritative server readback.

        Raises:
            HomeAssistantError: If validation fails, the device is unavailable or the API rejects the write.
        """
        if not self.available:
            msg = "Cannot rename a NOTTY device without current cloud-name readback"
            raise HomeAssistantError(msg)
        try:
            alias_payload(self.device_id, value)
            if value == self.native_value:
                return
            await self.coordinator.api.set_device_alias(self.device_id, value)
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.async_request_refresh()
