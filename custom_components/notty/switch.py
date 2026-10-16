from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from custom_components.notty.api import NottyApiError, dnd_payload
from custom_components.notty.binary_sensor import TRUE_VALUES
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import NottyEntity, merged_device_data, value_from_block
from custom_components.notty.models import DeviceData, NottyConfigEntry

DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"
ACTION_SET_DND = "set_dnd"


@dataclass(frozen=True, kw_only=True)
class NottySwitchDescription(SwitchEntityDescription):
    action: str
    field: str
    on_value: int = 1
    off_value: int = 0


SWITCHES = (
    NottySwitchDescription(key="switch_key", name="Child Lock", action="set_key", field="switch"),
    NottySwitchDescription(key="switch_dnd", name="Do Not Disturb", action="set_dnd", field="switch"),
)


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Async setup entry."""
    coordinator = entry.runtime_data
    entities: list[NottySwitch] = []
    for device_id, block in coordinator.data.items():
        if block.get("type") != DEVICE_TYPE_LITTER_BOX:
            continue
        if block["device"].get("_notty_source") == SOURCE_PET:
            continue
        entities.extend(
            NottySwitch(coordinator, device_id, block["device"], description)
            for description in SWITCHES
            if value_from_block(block, description.key) is not None
        )
    async_add_entities(entities)


class NottySwitch(NottyEntity, SwitchEntity):
    entity_description: NottySwitchDescription

    def __init__(
        self, coordinator: NottyCoordinator, device_id: str, device: DeviceData, description: NottySwitchDescription
    ) -> None:
        super().__init__(coordinator, device_id, device)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{device_id}_setting_{description.key}"

    @property
    def is_on(self) -> bool:
        """Is on.

        Returns:
            bool: The resulting is on.
        """
        return value_from_block(self.block, self.entity_description.key) in TRUE_VALUES

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Extra state attributes.

        Returns:
            DeviceData | None: The resulting extra state attributes.
        """
        return {"raw_value": value_from_block(self.block, self.entity_description.key)}

    async def async_turn_on(self, **_kwargs: object) -> None:
        """Async turn on."""
        await self._async_set_enabled(enabled=True)

    async def async_turn_off(self, **_kwargs: object) -> None:
        """Async turn off."""
        await self._async_set_enabled(enabled=False)

    async def _async_set_enabled(self, *, enabled: bool) -> None:
        value = self.entity_description.on_value if enabled else self.entity_description.off_value
        data: DeviceData = {self.entity_description.field: value}
        if self.entity_description.action == ACTION_SET_DND:
            try:
                data = dnd_payload(merged_device_data(self.block), switch_dnd=value)
            except NottyApiError as exc:
                raise HomeAssistantError(str(exc)) from exc
        await self.coordinator.api.litter_action(self.device_id, self.entity_description.action, data)
        await self.coordinator.async_request_refresh()
