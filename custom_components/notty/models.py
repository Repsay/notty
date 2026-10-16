"""Types shared by platform entities and the update coordinator."""

from typing import TYPE_CHECKING, TypedDict

from homeassistant.config_entries import ConfigEntry

from custom_components.notty.api import JsonObject

if TYPE_CHECKING:
    from custom_components.notty.coordinator import NottyCoordinator

type DeviceData = JsonObject


class DeviceBlock(TypedDict):
    """One physical device or pet and its latest response."""

    device: DeviceData
    info: DeviceData
    type: str


type CoordinatorData = dict[str, DeviceBlock]
type NottyConfigEntry = ConfigEntry[NottyCoordinator]
