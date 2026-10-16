from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import matches_value
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity, value_from_block
from custom_components.notty.models import DeviceData, NottyConfigEntry

SOURCE_PET = "pet"


def _litter_device_id(current: DeviceData) -> str | None:
    for key in ("_notty_litter_user_device_id", "litter_user_device_id"):
        value = current.get(key)
        if not matches_value(value, (None, "", 0, "0")):
            return str(value)

    pet_devices = current.get("pet_devices")
    if isinstance(pet_devices, list):
        for device in pet_devices:
            if not isinstance(device, dict):
                continue
            for key in ("user_device_id", "device_id", "id", "did"):
                value = device.get(key)
                if not matches_value(value, (None, "", 0, "0")):
                    return str(value)
    return None


@dataclass(frozen=True, kw_only=True)
class NottyNumberDescription(NumberEntityDescription):
    native_min_value: float = 0.5
    native_max_value: float = 15.0
    native_step: float = 0.1


NUMBERS = (NottyNumberDescription(key="weight", name="Weight", native_unit_of_measurement=UnitOfMass.KILOGRAMS),)


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Async setup entry."""
    coordinator = entry.runtime_data
    entities: list[NottyPetNumber] = []
    for device_id, block in coordinator.data.items():
        if block["device"].get("_notty_source") != SOURCE_PET:
            continue
        pet_id = block["device"].get("pet_id")
        if matches_value(pet_id, (None, "")):
            continue
        entities.extend(
            NottyPetNumber(coordinator, device_id, block["device"], description)
            for description in NUMBERS
            if value_from_block(block, description.key) is not None
        )
    async_add_entities(entities)


class NottyPetNumber(NottyEntity, NumberEntity):
    entity_description: NottyNumberDescription

    def __init__(
        self, coordinator: NottyCoordinator, device_id: str, device: DeviceData, description: NottyNumberDescription
    ) -> None:
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step

    @property
    def native_value(self) -> float | None:
        """Native value.

        Returns:
            float | None: The resulting native value.
        """
        value = value_from_block(self.block, self.entity_description.key)
        if value is None:
            value = value_from_block(self.block, "today_weight")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @property
    def available(self) -> bool:
        """Available.

        Returns:
            bool: The resulting available.
        """
        if not super().available:
            return False
        current = {**self.block.get("device", {}), **self.block.get("info", {})}
        litter_device_id = _litter_device_id(current)
        has_litter_binding = bool(
            litter_device_id or current.get("bind_litter_box") or current.get("has_litter_box_data")
        )
        return not has_litter_binding or bool(litter_device_id)

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Extra state attributes.

        Returns:
            DeviceData | None: The resulting extra state attributes.
        """
        current = {**self.block.get("device", {}), **self.block.get("info", {})}
        return {
            "write_supported": self.available,
            "litter_user_device_id": _litter_device_id(current),
            "requires_litter_box_binding": True,
        }

    async def async_set_native_value(self, value: float) -> None:
        """Async set native value."""
        pet_id = str(self.device.get("pet_id") or "").removeprefix("pet_")
        current = {**self.block.get("device", {}), **self.block.get("info", {})}
        await self.coordinator.api.save_pet_weight(pet_id, value, current)
        await self.coordinator.async_request_refresh()
