from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

from .binary_sensor import TRUE_VALUES
from .entity import NottyEntity, value_from_block


@dataclass(frozen=True, kw_only=True)
class NottySwitchDescription(SwitchEntityDescription):
    action: str
    field: str
    on_value: Any = 1
    off_value: Any = 0


SWITCHES = (
    NottySwitchDescription(
        key="switch_key", name="Child Lock", action="set_key", field="switch_key"
    ),
    NottySwitchDescription(
        key="switch_dnd", name="Do Not Disturb", action="set_dnd", field="switch_dnd"
    ),
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
            NottySwitch(coordinator, device_id, block["device"], description)
            for description in SWITCHES
            if value_from_block(block, description.key) is not None
        )
    async_add_entities(entities)


class NottySwitch(NottyEntity, SwitchEntity):
    entity_description: NottySwitchDescription

    def __init__(self, coordinator, device_id, device, description: NottySwitchDescription):
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"

    @property
    def is_on(self):
        return value_from_block(self.block, self.entity_description.key) in TRUE_VALUES

    @property
    def extra_state_attributes(self):
        return {"raw_value": value_from_block(self.block, self.entity_description.key)}

    async def async_turn_on(self, **kwargs):
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool):
        value = self.entity_description.on_value if enabled else self.entity_description.off_value
        data = {self.entity_description.field: value}
        if self.entity_description.action == "set_dnd":
            data.update(
                {
                    "dnd_begin_time": value_from_block(self.block, "dnd_begin_time") or "00:00",
                    "dnd_end_time": value_from_block(self.block, "dnd_end_time") or "00:00",
                }
            )
        await self.coordinator.api.litter_action(
            self.device_id,
            self.entity_description.action,
            data,
        )
        await self.coordinator.async_request_refresh()
