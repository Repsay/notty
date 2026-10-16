from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import NottyEntity, merged_device_data, title_from_key, value_from_block

BINARY_KEYS = {
    "online",
    "is_online",
    "locked",
    "child_lock",
    "dnd",
    "switch_dnd",
    "switch_key",
    "open_litter_remind",
    "open_garbagebag_remind",
    "garbage_bag_switch",
    "switch_litter",
    "switch_ozone",
    "switch_voice",
    "uvc_switch",
    "led",
    "filter",
    "desiccant",
    "bind_litter_box",
    "has_litter_box_data",
}
IGNORED_BINARY_KEYS = {
    "_notty_has_device_id",
    "bind_feeder",
    "bind_water_dispenser",
    "has_feeder_data",
    "has_water_dispenser_data",
    "is_default",
    "is_owner",
    "show_card",
}
TRUE_VALUES = {True, 1, "1", "true", "True", "TRUE", "online", "on", "open", "yes"}
BOOLEAN_VALUES = {True, False, 0, 1, "0", "1", "true", "false", "True", "False", "TRUE", "FALSE"}
BOOLEAN_PREFIXES = ("switch_", "open_")
BOOLEAN_SUFFIXES = ("_switch",)


def looks_boolean_key(key: str, value) -> bool:
    if isinstance(value, (dict, list, set, tuple)):
        return False
    try:
        if value not in BOOLEAN_VALUES:
            return False
    except TypeError:
        return False
    return key.startswith(BOOLEAN_PREFIXES) or key.endswith(BOOLEAN_SUFFIXES)


def _binary_keys(block: dict) -> list[str]:
    merged = merged_device_data(block)
    keys = set(BINARY_KEYS).intersection(merged)
    keys.update(key for key, value in merged.items() if isinstance(value, bool))
    keys.update(key for key, value in merged.items() if looks_boolean_key(key, value))
    keys.difference_update(IGNORED_BINARY_KEYS)
    return sorted(keys)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for device_id, block in coordinator.data.items():
        for key in _binary_keys(block):
            entities.append(NottyBinary(coordinator, device_id, block["device"], key))
    async_add_entities(entities)


class NottyBinary(NottyEntity, BinarySensorEntity):
    def __init__(self, coordinator, device_id, device, key):
        super().__init__(coordinator, device_id, device)
        self.key = key
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_name = title_from_key(key)
        if key in {"online", "is_online"}:
            self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        elif key in {"locked", "child_lock", "switch_key"}:
            self._attr_device_class = BinarySensorDeviceClass.LOCK

    @property
    def is_on(self):
        return value_from_block(self.block, self.key) in TRUE_VALUES

    @property
    def extra_state_attributes(self):
        return {"raw_value": value_from_block(self.block, self.key)}
