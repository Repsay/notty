from __future__ import annotations

from typing import cast

from homeassistant.helpers.device_registry import DeviceInfo, async_get
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.notty.api import JsonValue
from custom_components.notty.const import DOMAIN
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.models import DeviceBlock, DeviceData


def merged_device_data(block: DeviceBlock) -> DeviceData:
    """Merged device data.

    Returns:
        DeviceData: The resulting merged device data.
    """
    return {**block.get("device", {}), **block.get("info", {})}


def value_from_block(block: DeviceBlock, key: str) -> JsonValue:
    """Value from block.

    Returns:
        JsonValue: The resulting value from block.
    """
    return block.get("info", {}).get(key, block.get("device", {}).get(key))


def title_from_key(key: str) -> str:
    """Title from key.

    Returns:
        str: The resulting title from key.
    """
    aliases = {
        "dnd": "Do Not Disturb",
        "default_remaining_days": "Litter Renewal Remaining Days",
        "garbage_bag_cycle_time": "Trash Bag Reminder Interval",
        "garbage_bag_remaining_days": "Trash Bag Remaining Days",
        "lb_today_clean_count": "Today Clean Count",
        "lb_mode": "Mode",
        "lb_status": "Status",
        "litter_pet_names": "Litter Pet Names",
        "litter_user_device_id": "Litter Box Device ID",
        "latest_daily_event_count": "Latest Daily Event Count",
        "latest_daily_event_date": "Latest Daily Event Date",
        "daily_events_average": "Daily Event Average",
        "daily_events_last_7_days": "Daily Events Last 7 Days",
        "daily_events_last_30_days": "Daily Events Last 30 Days",
        "latest_event_date": "Latest Event Date",
        "latest_event_datetime": "Latest Event Date Time",
        "latest_event_event": "Latest Event",
        "latest_event_event_type_id": "Latest Event Type",
        "latest_event_raw_date": "Latest Event Raw Date",
        "latest_event_raw_time": "Latest Event Raw Time",
        "latest_event_time": "Latest Event Time",
        "latest_message_date_created": "Latest Message Date",
        "latest_message_date_created_raw": "Latest Message Raw Date",
        "latest_message_sub_title": "Latest Message Subtitle",
        "latest_message_title": "Latest Message Title",
        "latest_toilet_event": "Latest Toilet Event",
        "latest_toilet_event_date": "Latest Toilet Event Date",
        "latest_toilet_event_datetime": "Latest Toilet Event Date Time",
        "latest_toilet_event_duration": "Latest Toilet Event Duration",
        "latest_toilet_event_pet_name": "Latest Toilet Event Pet Name",
        "latest_toilet_event_raw_date": "Latest Toilet Event Raw Date",
        "latest_toilet_event_raw_time": "Latest Toilet Event Raw Time",
        "latest_toilet_event_time": "Latest Toilet Event Time",
        "memos_count": "Memos Count",
        "mode": "Mode",
        "plan_times": "Plan Times",
        "remaining_days": "Litter Renewal Remaining Days",
        "status": "Status",
        "status_id": "Connection Status",
        "language": "Language",
        "weight_unit": "Weight Unit",
        "today_wc_count": "Today Toileting Count",
        "today_wc_duration": "Today Toileting Duration",
        "today_weight": "Today Weight",
        "pet_data_detail_today_wc_count": "Today Toileting Count",
        "pet_data_detail_today_wc_duration": "Today Toileting Duration",
        "pet_data_detail_yesterday_wc_count": "Yesterday Toileting Count",
        "pet_data_detail_yesterday_wc_duration": "Yesterday Toileting Duration",
        "pet_data_statistics_duration_total": "Toileting Duration Total",
        "pet_data_statistics_duration_max": "Toileting Duration Max",
        "pet_data_statistics_duration_nonzero_count": "Toileting Session Count",
        "pet_data_statistics_duration_latest": "Latest Toileting Duration Slot",
        "pet_data_statistics_duration_latest_time": "Latest Toileting Duration Slot Time",
        "pet_data_statistics_duration_latest_nonzero": "Latest Toileting Duration",
        "pet_data_statistics_duration_latest_nonzero_time": "Latest Toileting Time",
        "wc_statistics_duration_total": "Toileting Duration Total",
        "wc_statistics_duration_max": "Toileting Duration Max",
        "wc_statistics_duration_nonzero_count": "Toileting Session Count",
        "wc_statistics_duration_latest": "Latest Toileting Duration Slot",
        "wc_statistics_duration_latest_time": "Latest Toileting Duration Slot Time",
        "wc_statistics_duration_latest_nonzero": "Latest Toileting Duration",
        "wc_statistics_duration_latest_nonzero_time": "Latest Toileting Time",
        "unread_message_count": "Unread Message Count",
        "uvc_switch": "UVC",
        "wc_status": "Toilet Use Status",
        "wc_statistics_count": "Toileting Statistics Count",
    }
    return aliases.get(key, key.replace("_", " ").title())


FIELD_VIA_DEVICE_ID = "via_device_id"


class NottyEntity(CoordinatorEntity[NottyCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: NottyCoordinator, device_id: str, device: DeviceData) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self.device = device
        device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=str(device.get("alias") or device.get("name") or f"NOTTY {device_id}"),
            manufacturer="NOTTY",
            model=str(device.get("model") or device.get("product_name") or device.get("device_name") or ""),
            sw_version=str(device.get("version") or device.get("firmware_version") or ""),
        )
        parent_device_id = device.get("_notty_litter_user_device_id")
        if parent_device_id and coordinator.entry_id is not None:
            registry = async_get(coordinator.hass)
            if hasattr(registry, "async_get_device_by_identifier"):
                parent = registry.async_get_device_by_identifier((DOMAIN, str(parent_device_id)), coordinator.entry_id)
            else:
                parent = registry.async_get_device(identifiers={(DOMAIN, str(parent_device_id))})
            if parent is not None:
                if FIELD_VIA_DEVICE_ID in DeviceInfo.__annotations__:
                    device_info["via_device_id"] = parent.id
                else:
                    device_info.update(cast("DeviceInfo", {"via_device": (DOMAIN, str(parent_device_id))}))
        self._attr_device_info = device_info

    @property
    def block(self) -> DeviceBlock:
        """Block.

        Returns:
            DeviceBlock: The resulting block.
        """
        return self.coordinator.data.get(self.device_id, {"device": {}, "info": {}, "type": ""})

    @property
    def available(self) -> bool:
        """Available.

        Returns:
            bool: The resulting available.
        """
        return super().available and self.device_id in (self.coordinator.data or {})

    def update_device_name(self, name: str) -> None:
        """Refresh the integration-provided name while preserving the HA user override."""
        if self.coordinator.entry_id is None:
            return
        registry = async_get(self.hass)
        if hasattr(registry, "async_get_device_by_identifier"):
            device = registry.async_get_device_by_identifier((DOMAIN, self.device_id), self.coordinator.entry_id)
        else:
            device = registry.async_get_device(identifiers={(DOMAIN, self.device_id)})
        if device is not None and device.name != name:
            registry.async_update_device(device.id, name=name)
