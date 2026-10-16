from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import UnitOfMass

from .entity import NottyEntity, value_from_block


def _litter_device_id(current: dict) -> str | None:
    for key in ("_notty_litter_user_device_id", "litter_user_device_id"):
        value = current.get(key)
        if value not in (None, "", 0, "0", False):
            return str(value)

    pet_devices = current.get("pet_devices")
    if isinstance(pet_devices, list):
        for device in pet_devices:
            if not isinstance(device, dict):
                continue
            for key in ("user_device_id", "device_id", "id", "did"):
                value = device.get(key)
                if value not in (None, "", 0, "0", False):
                    return str(value)
    return None


@dataclass(frozen=True, kw_only=True)
class NottyNumberDescription(NumberEntityDescription):
    min_value: float = 0.5
    max_value: float = 15.0
    step: float = 0.1


NUMBERS = (
    NottyNumberDescription(
        key="weight",
        name="Weight",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for device_id, block in coordinator.data.items():
        if block["device"].get("_notty_source") != "pet":
            continue
        pet_id = block["device"].get("pet_id")
        if pet_id in (None, ""):
            continue
        entities.extend(
            NottyPetNumber(coordinator, device_id, block["device"], description)
            for description in NUMBERS
            if value_from_block(block, description.key) is not None
        )
    async_add_entities(entities)


class NottyPetNumber(NottyEntity, NumberEntity):
    entity_description: NottyNumberDescription

    def __init__(self, coordinator, device_id, device, description: NottyNumberDescription):
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step

    @property
    def native_value(self):
        value = value_from_block(self.block, self.entity_description.key)
        if value is None:
            value = value_from_block(self.block, "today_weight")
        return value

    @property
    def available(self):
        if not super().available:
            return False
        current = {**self.block.get("device", {}), **self.block.get("info", {})}
        litter_device_id = _litter_device_id(current)
        has_litter_binding = bool(
            litter_device_id or current.get("bind_litter_box") or current.get("has_litter_box_data")
        )
        return not has_litter_binding or bool(litter_device_id)

    @property
    def extra_state_attributes(self):
        current = {**self.block.get("device", {}), **self.block.get("info", {})}
        return {
            "write_supported": self.available,
            "litter_user_device_id": _litter_device_id(current),
            "requires_litter_box_binding": True,
        }

    async def async_set_native_value(self, value: float):
        pet_id = str(self.device.get("pet_id") or "").removeprefix("pet_")
        current = {**self.block.get("device", {}), **self.block.get("info", {})}
        await self.coordinator.api.save_pet_weight(pet_id, value, current)
        await self.coordinator.async_request_refresh()
