# ruff: file-ignore[stdlib-module-shadowing] -- Home Assistant requires this platform module name.
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import JsonValue
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity, value_from_block
from custom_components.notty.models import DeviceBlock, DeviceData, NottyConfigEntry

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"
FIELD_AUTO_DELAY = "auto_delay"
FIELD_MODE = "mode"


@dataclass(frozen=True, kw_only=True)
class NottySelectDescription(SelectEntityDescription):
    action: str
    field: str
    value_options: dict[int, str]
    fallback_key: str | None = None
    unit: str | None = None


SELECTS = (
    NottySelectDescription(
        key="auto_delay",
        name="Automatic cleaning delay",
        action="set_auto_delay",
        field="delay",
        value_options={minutes: f"{minutes} minute" + ("s" if minutes != 1 else "") for minutes in range(1, 16)},
        unit="minutes",
        entity_category=EntityCategory.CONFIG,
    ),
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
        key="language", name="Screen Language", action="set_language", field="language", value_options={1: "English"}
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


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Async setup entry."""
    coordinator = entry.runtime_data
    entities: list[NottySelect] = []
    for device_id, block in coordinator.data.items():
        if block.get("type") != DEVICE_TYPE_LITTER_BOX:
            continue
        if block["device"].get("_notty_source") == SOURCE_PET:
            continue
        entities.extend(
            NottySelect(coordinator, device_id, block["device"], description)
            for description in SELECTS
            if _raw_value(block, description) is not None
        )
    async_add_entities(entities)


def _raw_value(block: DeviceBlock, description: NottySelectDescription) -> JsonValue:
    value = value_from_block(block, description.key)
    if value is None and description.fallback_key:
        value = value_from_block(block, description.fallback_key)
    return value


def _as_int(value: JsonValue) -> JsonValue:
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


class NottySelect(NottyEntity, SelectEntity):
    entity_description: NottySelectDescription

    def __init__(
        self, coordinator: NottyCoordinator, device_id: str, device: DeviceData, description: NottySelectDescription
    ) -> None:
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"

    @property
    def current_option(self) -> str | None:
        """Current option.

        Returns:
            str | None: The resulting current option.
        """
        value = _as_int(_raw_value(self.block, self.entity_description))
        if isinstance(value, int) and value in self.entity_description.value_options:
            return self.entity_description.value_options[value]
        if self.entity_description.key == FIELD_AUTO_DELAY:
            return None
        if self.entity_description.unit and value is not None:
            return f"{value} {self.entity_description.unit}"
        return f"{self.entity_description.name} {value}"

    @property
    def options(self) -> list[str]:
        """Options.

        Returns:
            list[str]: The resulting options.
        """
        options = list(self.entity_description.value_options.values())
        current = self.current_option
        if current is not None and current not in options:
            options.append(current)
        return options

    @property
    def available(self) -> bool:
        """Available.

        Returns:
            bool: The resulting available.
        """
        if self.entity_description.key == FIELD_AUTO_DELAY:
            mode = value_from_block(self.block, "mode")
            if mode is None:
                mode = value_from_block(self.block, "lb_mode")
            return (
                super().available and _as_int(mode) == 1 and _raw_value(self.block, self.entity_description) is not None
            )
        return super().available

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Extra state attributes.

        Returns:
            DeviceData | None: The resulting extra state attributes.
        """
        attrs: DeviceData = {"raw_value": _raw_value(self.block, self.entity_description)}
        if self.entity_description.unit:
            attrs["unit"] = self.entity_description.unit
        return attrs

    async def async_select_option(self, option: str) -> None:
        """Async select option.

        Raises:
            HomeAssistantError: When the requested operation cannot be completed.
        """
        if self.entity_description.key == FIELD_AUTO_DELAY and not self.available:
            msg = "NOTTY cleaning delay can only be changed in Auto mode with current device data"
            raise HomeAssistantError(msg)
        if self.entity_description.key == FIELD_MODE:
            msg = (
                "NOTTY mode changes are disabled until remaining mode codes and "
                "the set_mode endpoint have been verified"
            )
            raise HomeAssistantError(msg)
        reverse = {label: value for value, label in self.entity_description.value_options.items()}
        if option not in reverse:
            if self.entity_description.key == FIELD_AUTO_DELAY:
                msg = "NOTTY cleaning delay must be between 1 and 15 minutes"
                raise HomeAssistantError(msg)
            return
        await self.coordinator.api.litter_action(
            self.device_id, self.entity_description.action, {self.entity_description.field: reverse[option]}
        )
        await self.coordinator.async_request_refresh()
