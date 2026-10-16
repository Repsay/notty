# ruff: file-ignore[stdlib-module-shadowing] -- Home Assistant requires this platform module name.
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import NottyApiError, dnd_local_time, dnd_payload
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity, merged_device_data, value_from_block
from custom_components.notty.models import DeviceData, NottyConfigEntry

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"
MIN_TIME_PARTS = 2


@dataclass(frozen=True, kw_only=True)
class NottyTimeDescription(TimeEntityDescription):
    pass


TIMES = (
    NottyTimeDescription(key="dnd_begin_time", name="Do Not Disturb Start"),
    NottyTimeDescription(key="dnd_end_time", name="Do Not Disturb End"),
)


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Async setup entry."""
    coordinator = entry.runtime_data
    entities: list[NottyTime] = []
    for device_id, block in coordinator.data.items():
        if block.get("type") != DEVICE_TYPE_LITTER_BOX:
            continue
        if block["device"].get("_notty_source") == SOURCE_PET:
            continue
        entities.extend(
            NottyTime(coordinator, device_id, block["device"], description)
            for description in TIMES
            if _parse_time(value_from_block(block, description.key)) is not None
        )
    async_add_entities(entities)


def _parse_time(value: object) -> time | None:
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) < MIN_TIME_PARTS:
        return None
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def _format_time(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


class NottyTime(NottyEntity, TimeEntity):
    entity_description: NottyTimeDescription

    def __init__(
        self, coordinator: NottyCoordinator, device_id: str, device: DeviceData, description: NottyTimeDescription
    ) -> None:
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"

    @property
    def native_value(self) -> time | None:
        """Native value.

        Returns:
            time | None: The resulting native value.
        """
        try:
            return dnd_local_time(
                value_from_block(self.block, self.entity_description.key), self.coordinator.hass.config.time_zone
            )
        except NottyApiError:
            return None

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Extra state attributes.

        Returns:
            DeviceData | None: The resulting extra state attributes.
        """
        return {"raw_value": value_from_block(self.block, self.entity_description.key)}

    async def async_set_value(self, value: time) -> None:
        """Async set value.

        Raises:
            HomeAssistantError: When the requested operation cannot be completed.
        """
        try:
            current = merged_device_data(self.block)
            local_zone = self.coordinator.hass.config.time_zone
            if self.entity_description.key == "dnd_begin_time":
                data = dnd_payload(
                    current, time_zone=local_zone, input_time_zone=local_zone, dnd_begin_time=_format_time(value)
                )
            else:
                data = dnd_payload(
                    current, time_zone=local_zone, input_time_zone=local_zone, dnd_end_time=_format_time(value)
                )
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.api.litter_action(self.device_id, "set_dnd", data)
        await self.coordinator.async_request_refresh()
