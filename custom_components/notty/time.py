from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription

from .entity import NottyEntity, value_from_block


@dataclass(frozen=True, kw_only=True)
class NottyTimeDescription(TimeEntityDescription):
    pass


TIMES = (
    NottyTimeDescription(key="dnd_begin_time", name="Do Not Disturb Start"),
    NottyTimeDescription(key="dnd_end_time", name="Do Not Disturb End"),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for device_id, block in coordinator.data.items():
        if block.get("type") != "litter_box":
            continue
        if block["device"].get("_notty_source") == "pet":
            continue
        entities.extend(
            NottyTime(coordinator, device_id, block["device"], description)
            for description in TIMES
            if _parse_time(value_from_block(block, description.key)) is not None
        )
    async_add_entities(entities)


def _parse_time(value) -> time | None:
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def _format_time(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


class NottyTime(NottyEntity, TimeEntity):
    entity_description: NottyTimeDescription

    def __init__(self, coordinator, device_id, device, description: NottyTimeDescription):
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"

    @property
    def native_value(self):
        return _parse_time(value_from_block(self.block, self.entity_description.key))

    @property
    def extra_state_attributes(self):
        return {"raw_value": value_from_block(self.block, self.entity_description.key)}

    async def async_set_value(self, value: time):
        data = {
            "switch_dnd": value_from_block(self.block, "switch_dnd") or 0,
            "dnd_begin_time": value_from_block(self.block, "dnd_begin_time") or "00:00",
            "dnd_end_time": value_from_block(self.block, "dnd_end_time") or "00:00",
            self.entity_description.key: _format_time(value),
        }
        await self.coordinator.api.litter_action(self.device_id, "set_dnd", data)
        await self.coordinator.async_request_refresh()
