from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .entity import NottyEntity


@dataclass(frozen=True, kw_only=True)
class NottyButtonDescription(ButtonEntityDescription):
    device_type: str
    one_key: Any | None = None
    endpoint: str | None = None


BUTTONS = (
    NottyButtonDescription(key="clean", name="Clean", device_type="litter_box", one_key=0),
    NottyButtonDescription(key="level", name="Level litter", device_type="litter_box", one_key=1),
    NottyButtonDescription(key="empty", name="Empty litter", device_type="litter_box", one_key=2),
    NottyButtonDescription(key="sterilize", name="Sterilize", device_type="litter_box", one_key=3),
    NottyButtonDescription(
        key="reset_litter_reminder",
        name="Reset litter renewal reminder",
        device_type="litter_box",
        endpoint="/device/litter_box/set_litter_remind",
    ),
    NottyButtonDescription(
        key="reset_garbage_bag_reminder",
        name="Reset trash bag reminder",
        device_type="litter_box",
        endpoint="/device/litter_box/set_garbage_bag_remind",
    ),
    NottyButtonDescription(
        key="reset_device_weight",
        name="Reset device weight",
        device_type="litter_box",
        endpoint="/device/litter_box/reset_device_weight",
    ),
    NottyButtonDescription(
        key="horizontal_calibration",
        name="Horizontal calibration",
        device_type="litter_box",
        endpoint="/device/litter_box/horizontal_calibration",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for device_id, block in coordinator.data.items():
        device_type = block.get("type")
        if block["device"].get("_notty_source") == "pet":
            continue
        entities.extend(
            NottyButton(coordinator, device_id, block["device"], description)
            for description in BUTTONS
            if description.device_type == device_type
        )
    async_add_entities(entities)


class NottyButton(NottyEntity, ButtonEntity):
    entity_description: NottyButtonDescription

    def __init__(self, coordinator, device_id, device, description: NottyButtonDescription):
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_{description.key}"

    async def async_press(self):
        if self.entity_description.one_key is not None:
            await self.coordinator.api.command(
                self.device_id,
                self.entity_description.one_key,
                self.entity_description.device_type,
            )
        elif self.entity_description.endpoint:
            await self.coordinator.api.endpoint_action(
                self.device_id,
                self.entity_description.endpoint,
            )
        await self.coordinator.async_request_refresh()
