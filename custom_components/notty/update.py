"""Read-only firmware availability from the NOTTY upgrade-check response."""

from __future__ import annotations

from typing import override

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import JsonObject, JsonValue
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity, value_from_block
from custom_components.notty.models import DeviceBlock, DeviceData, NottyConfigEntry

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"
MAX_VERSION_LENGTH = 255
FIELD_SOURCE_VERSION = "src_version"
FIELD_DESTINATION_VERSION = "dest_version"


def firmware_data(block: DeviceBlock) -> JsonObject:
    """Read the current endpoint response without falling back to stale summaries.

    Returns:
        Upgrade metadata, or an empty object if the optional endpoint is unavailable.
    """
    related = block["info"].get("_notty_related")
    value = related.get("upgrade") if isinstance(related, dict) else None
    return value if isinstance(value, dict) else {}


def firmware_version(value: JsonValue) -> str | None:
    """Accept bounded firmware strings without inventing semantic version ordering.

    Returns:
        A nonempty printable version, otherwise None.
    """
    if not isinstance(value, str):
        return None
    version = value.strip()
    return version if version and len(version) <= MAX_VERSION_LENGTH and version.isprintable() else None


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async platform setup callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Discover supported firmware metadata now and after optional endpoint recovery."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    def discover() -> None:
        """Add a firmware entity once a physical box reports upgrade metadata."""
        entities: list[NottyFirmwareUpdate] = []
        for device_id, block in coordinator.data.items():
            if device_id in known or block["type"] != DEVICE_TYPE_LITTER_BOX:
                continue
            if block["device"].get("_notty_source") == SOURCE_PET:
                continue
            metadata = firmware_data(block)
            if FIELD_SOURCE_VERSION not in metadata or FIELD_DESTINATION_VERSION not in metadata:
                continue
            entities.append(NottyFirmwareUpdate(coordinator, device_id, block["device"]))
            known.add(device_id)
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class NottyFirmwareUpdate(NottyEntity, UpdateEntity):
    """Report upgrade availability without offering installation or guessed progress."""

    _attr_translation_key = "firmware"
    _attr_name = "Firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, coordinator: NottyCoordinator, device_id: str, device: DeviceData) -> None:
        super().__init__(coordinator, device_id, device)
        self._attr_unique_id = f"{device_id}_firmware"

    @property
    def installed_version(self) -> str | None:
        """The installed-version field from the current check response.

        Returns:
            The reported source version.
        """
        return firmware_version(firmware_data(self.block).get("src_version"))

    @property
    def latest_version(self) -> str | None:
        """Use the app's empty destination marker for no offered update.

        Returns:
            The offered version, current version for an explicit empty marker, or None.
        """
        destination = firmware_data(self.block).get("dest_version")
        if isinstance(destination, str) and not destination:
            return self.installed_version
        return firmware_version(destination)

    @property
    def release_summary(self) -> str | None:
        """The app's firmware description, without fetching external URLs.

        Returns:
            A summary bounded to Home Assistant's 255-character limit.
        """
        description = firmware_data(self.block).get("firmware_desc")
        return description[:255] if isinstance(description, str) and description else None

    @property
    def available(self) -> bool:
        """Require fresh usable metadata and honor explicit offline readback.

        Returns:
            Whether current version availability can be reported.
        """
        for key in ("online", "is_online"):
            value = value_from_block(self.block, key)
            if isinstance(value, (bool, int, str)) and value in {False, "0", "false", "offline"}:
                return False
        return super().available and self.installed_version is not None and self.latest_version is not None

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Keep cloud task status visible without interpreting it as measured progress.

        Returns:
            Only the reported task-status string, without task IDs or arbitrary response fields.
        """
        status = firmware_data(self.block).get("task_status")
        return {"task_status": status} if isinstance(status, str) else None

    @override
    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Follow offered target versions rather than assume a semantic version scheme.

        Returns:
            Whether the offered firmware differs from the installed firmware.
        """
        return latest_version != installed_version
