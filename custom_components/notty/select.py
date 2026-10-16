from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.exceptions import HomeAssistantError

from .entity import NottyEntity, value_from_block


@dataclass(frozen=True, kw_only=True)
class NottySelectDescription(SelectEntityDescription):
    action: str
    field: str
    value_options: dict[int, str]
    fallback_key: str | None = None
    unit: str | None = None


SELECTS = (
    NottySelectDescription(
        key="mode",
        name="Mode",
        action="set_mode",
        field="mode",
        # Mode 1 is verified as Auto against the owner's NOTTY app.
        # Remaining codes are unknown: do not publish guessed mode labels.
        value_options={1: "Auto"},
        fallback_key="lb_mode",
    ),
    NottySelectDescription(
        key="language",
        name="Screen Language",
        action="set_language",
        field="language",
        value_options={
            1: "English",
        },
    ),
    NottySelectDescription(
        key="default_remaining_days",
        name="Litter renewal reminder interval",
        action="set_litter_reminder_days",
        field="cycle_time",
        value_options={days: f"{days} days" for days in range(5, 31)},
        fallback_key="remaining_days",
        unit="days",
    ),
    NottySelectDescription(
        key="garbage_bag_cycle_time",
        name="Trash bag reminder interval",
        action="set_garbage_bag_reminder_days",
        field="cycle_time",
        value_options={days: f"{days} days" for days in range(2, 16)},
        fallback_key="garbage_bag_remaining_days",
        unit="days",
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
            NottySelect(coordinator, device_id, block["device"], description)
            for description in SELECTS
            if _raw_value(block, description) is not None
        )
    async_add_entities(entities)


def _raw_value(block: dict, description: NottySelectDescription):
    value = value_from_block(block, description.key)
    if value is None and description.fallback_key:
        value = value_from_block(block, description.fallback_key)
    return value


def _as_int(value):
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


class NottySelect(NottyEntity, SelectEntity):
    entity_description: NottySelectDescription

    def __init__(self, coordinator, device_id, device, description: NottySelectDescription):
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"

    @property
    def current_option(self):
        value = _as_int(_raw_value(self.block, self.entity_description))
        if value in self.entity_description.value_options:
            return self.entity_description.value_options[value]
        if self.entity_description.unit and value is not None:
            return f"{value} {self.entity_description.unit}"
        return f"{self.entity_description.name} {value}"

    @property
    def options(self):
        options = list(self.entity_description.value_options.values())
        current = self.current_option
        if current not in options:
            options.append(current)
        return options

    @property
    def extra_state_attributes(self):
        attrs = {"raw_value": _raw_value(self.block, self.entity_description)}
        if self.entity_description.unit:
            attrs["unit"] = self.entity_description.unit
        return attrs

    async def async_select_option(self, option: str):
        if self.entity_description.key == "mode":
            raise HomeAssistantError(
                "NOTTY mode changes are disabled until remaining mode codes and "
                "the set_mode endpoint have been verified"
            )
        reverse = {label: value for value, label in self.entity_description.value_options.items()}
        if option not in reverse:
            return
        await self.coordinator.api.litter_action(
            self.device_id,
            self.entity_description.action,
            {self.entity_description.field: reverse[option]},
        )
        await self.coordinator.async_request_refresh()
