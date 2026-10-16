from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import REMINDER_CYCLE_FIELDS, NottyApiError, reminder_payload
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity, value_from_block
from custom_components.notty.models import DeviceData, NottyConfigEntry

SOURCE_PET = "pet"


@dataclass(frozen=True, kw_only=True)
class NottyButtonDescription(ButtonEntityDescription):
    device_type: str
    one_key: int | None = None
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


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Async setup entry."""
    coordinator = entry.runtime_data
    entities: list[NottyButton] = []
    for device_id, block in coordinator.data.items():
        device_type = block.get("type")
        if block["device"].get("_notty_source") == SOURCE_PET:
            continue
        entities.extend(
            NottyButton(coordinator, device_id, block["device"], description)
            for description in BUTTONS
            if description.device_type == device_type
        )
    async_add_entities(entities)


class NottyButton(NottyEntity, ButtonEntity):
    entity_description: NottyButtonDescription

    def __init__(
        self, coordinator: NottyCoordinator, device_id: str, device: DeviceData, description: NottyButtonDescription
    ) -> None:
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_{description.key}"

    async def async_press(self) -> None:
        """Press the command or reset the reminder using its configured interval.

        Raises:
            HomeAssistantError: If the reminder interval cannot be preserved.
        """
        if self.entity_description.one_key is not None:
            await self.coordinator.api.command(
                self.device_id, self.entity_description.one_key, self.entity_description.device_type
            )
        elif self.entity_description.key in REMINDER_CYCLE_FIELDS:
            action = self.entity_description.key
            cycle = value_from_block(self.block, REMINDER_CYCLE_FIELDS[action])
            try:
                data = reminder_payload(action, {"cycle_time": cycle})
            except NottyApiError as exc:
                raise HomeAssistantError(str(exc)) from exc
            await self.coordinator.api.litter_action(self.device_id, action, data)
        elif self.entity_description.endpoint:
            await self.coordinator.api.endpoint_action(self.device_id, self.entity_description.endpoint)
        await self.coordinator.async_request_refresh()
