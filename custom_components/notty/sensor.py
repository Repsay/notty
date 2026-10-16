from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfMass, UnitOfTime

from .binary_sensor import BINARY_KEYS, looks_boolean_key
from .entity import NottyEntity, merged_device_data, title_from_key, value_from_block

SKIP_KEYS = {
    "id",
    "device_id",
    "user_device_id",
    "user_device_ids",
    "did",
    "mac",
    "name",
    "alias",
    "pet_id",
    "source_endpoint",
    "litter_user_device_id",
    "_notty_has_device_id",
    "_notty_pet_ids",
    "_notty_related",
    "_notty_source",
    "bind_feeder",
    "bind_water_dispenser",
    "has_feeder_data",
    "has_water_dispenser_data",
    "health_url",
    "image_path",
    "image_url",
    "product_name",
    "device_type",
    "show_card",
    "is_default",
    "is_owner",
    "weight",
    "mode",
    "lb_mode",
    "language",
    "default_remaining_days",
    "garbage_bag_cycle_time",
    "remaining_days",
    "cycle_time",
    "dnd_begin_time",
    "dnd_end_time",
    "token",
    "access_token",
}
NON_LITTER_PREFIXES = (
    "today_drink",
    "yesterday_drink",
    "diff_drink",
    "drink_",
    "today_eat",
    "yesterday_eat",
    "diff_eat",
    "eat_",
    "f_",
    "wd_",
    "water_",
    "feeder_",
)

WEIGHT_KEYS = {
    "today_weight",
    "yesterday_weight",
    "total_weight",
    "weight",
}
TIMESTAMP_KEYS = {
    "latest_message_date_created",
    "messages_date_created",
    "latest_event_datetime",
    "latest_toilet_event_datetime",
}
COUNT_KEYS = {
    "plans_count",
    "enabled_plans_count",
    "pet_data_list_count",
    "pet_data_statistics_count",
    "pet_data_detail_count",
    "associated_pets_count",
    "associated_users_count",
    "associated_shared_user_count",
    "memos_count",
    "wc_statistics_count",
    "events_count",
    "daily_event_counts_count",
    "latest_daily_event_count",
    "daily_events_total",
    "daily_events_last_7_days",
    "daily_events_last_30_days",
    "daily_events_average",
    "unread_message_count",
    "today_wc_count",
    "yesterday_wc_count",
    "pet_data_detail_today_wc_count",
    "pet_data_detail_yesterday_wc_count",
    "pet_data_statistics_duration_nonzero_count",
    "wc_statistics_duration_nonzero_count",
}
DURATION_KEYS = {
    "latest_toilet_event_duration",
    "today_wc_duration",
    "yesterday_wc_duration",
    "pet_data_detail_today_wc_duration",
    "pet_data_detail_yesterday_wc_duration",
    "pet_data_statistics_duration_total",
    "pet_data_statistics_duration_max",
    "pet_data_statistics_duration_latest",
    "pet_data_statistics_duration_latest_nonzero",
    "wc_statistics_duration_total",
    "wc_statistics_duration_max",
    "wc_statistics_duration_latest",
    "wc_statistics_duration_latest_nonzero",
}
RELATED_ATTRIBUTE_KEYS = {
    "plans_count": "plans",
    "pet_data_list_count": "pet_data_list",
    "pet_data_statistics_count": "pet_data_statistics",
    "pet_data_detail_count": "pet_data_detail",
    "associated_pets_count": "associated_pets",
    "associated_users_count": "associated_users",
    "memos_count": "memos",
    "wc_statistics_count": "wc_statistics",
    "events_count": "events",
}
MAX_STATE_LENGTH = 255
ENUM_LABELS = {
    "mode": {1: "Smart", 2: "Time", 3: "Auto"},
    "lb_mode": {1: "Smart", 2: "Time", 3: "Auto"},
    "status": {0: "Idle"},
    "lb_status": {0: "Idle"},
    "status_id": {0: "Offline", 1: "Online"},
    "language": {1: "English"},
    "weight_unit": {1: "kg", 2: "lb"},
    "sex": {0: "Unknown", 1: "Male", 2: "Female"},
}
ENUM_OPTIONS = {
    "mode": tuple(ENUM_LABELS["mode"].values()),
    "lb_mode": tuple(ENUM_LABELS["lb_mode"].values()),
    "status": tuple(ENUM_LABELS["status"].values()),
    "lb_status": tuple(ENUM_LABELS["lb_status"].values()),
    "status_id": tuple(ENUM_LABELS["status_id"].values()),
    "language": tuple(ENUM_LABELS["language"].values()),
    "weight_unit": tuple(ENUM_LABELS["weight_unit"].values()),
    "sex": tuple(ENUM_LABELS["sex"].values()),
    "latest_event_event_type_id": tuple(f"event_type_{value}" for value in range(0, 30)),
    "upgrade_task_status": tuple(f"task_status_{value}" for value in range(0, 10)),
}
ENUM_VALUE_PREFIX = {
    "lb_mode": "mode",
    "lb_status": "status",
}


def _is_scalar(value) -> bool:
    return value is not None and not isinstance(value, (dict, list, set, tuple))


def _valid_sensor_value(value) -> bool:
    return not isinstance(value, str) or len(value) <= MAX_STATE_LENGTH


def _sensor_keys(block: dict) -> list[str]:
    merged = merged_device_data(block)
    keys = []
    for key, value in merged.items():
        if (
            key in SKIP_KEYS
            or key in BINARY_KEYS
            or key.endswith("_str")
            or key.startswith(NON_LITTER_PREFIXES)
            or isinstance(value, bool)
            or not _is_scalar(value)
            or not _valid_sensor_value(value)
            or looks_boolean_key(key, value)
        ):
            continue
        keys.append(key)
    return sorted(keys)


def _number_or_original(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped) if "." in stripped else int(stripped)
        except ValueError:
            return value
    return value


def _is_numeric_value(value) -> bool:
    return isinstance(_number_or_original(value), (int, float)) and not isinstance(value, bool)


def _parse_timestamp_value(value):
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed


def _enum_value(key: str, value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            value = int(stripped)
    if key == "sex":
        return ENUM_LABELS["sex"].get(value, f"Sex {value}")
    if key in ENUM_LABELS:
        return ENUM_LABELS[key].get(value, f"{title_from_key(key)} {value}")
    prefix = ENUM_VALUE_PREFIX.get(key, key)
    return f"{prefix}_{value}"


def _sensor_metadata(key: str, raw_value):
    if key in TIMESTAMP_KEYS:
        timestamp_value = _parse_timestamp_value(raw_value)
        if timestamp_value is not None:
            return SensorDeviceClass.TIMESTAMP, None, None
    if key in WEIGHT_KEYS and _is_numeric_value(raw_value):
        return SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS, SensorStateClass.MEASUREMENT
    if key in COUNT_KEYS and _is_numeric_value(raw_value):
        return None, None, SensorStateClass.MEASUREMENT
    if key in DURATION_KEYS and _is_numeric_value(raw_value):
        return SensorDeviceClass.DURATION, UnitOfTime.SECONDS, SensorStateClass.MEASUREMENT
    if key in ENUM_OPTIONS:
        return SensorDeviceClass.ENUM, None, None
    return None, None, None


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = []
    for device_id, block in coordinator.data.items():
        for key in _sensor_keys(block):
            entities.append(NottySensor(coordinator, device_id, block["device"], key))
    async_add_entities(entities)


class NottySensor(NottyEntity, SensorEntity):
    def __init__(self, coordinator, device_id, device, key):
        super().__init__(coordinator, device_id, device)
        self.key = key
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_name = title_from_key(key)
        raw_value = value_from_block(self.block, self.key)
        device_class, unit, state_class = _sensor_metadata(key, raw_value)
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class

    @property
    def native_value(self):
        raw_value = value_from_block(self.block, self.key)
        timestamp_value = _parse_timestamp_value(raw_value)
        if timestamp_value is not None and (
            "datetime" in self.key
            or self.key in {"latest_message_date_created", "messages_date_created"}
        ):
            return timestamp_value
        if self.key in ENUM_OPTIONS:
            return _enum_value(self.key, raw_value)
        return _number_or_original(raw_value)

    @property
    def extra_state_attributes(self):
        attributes = {}
        if self.key in ENUM_OPTIONS:
            attributes["raw_value"] = value_from_block(self.block, self.key)
        source_key = RELATED_ATTRIBUTE_KEYS.get(self.key)
        if source_key:
            if source_key == "events":
                value = self.block.get("info", {}).get("events")
            else:
                value = self.block.get("info", {}).get("_notty_related", {}).get(source_key)
            if value:
                attributes[source_key] = value
        return attributes or None

    @property
    def options(self):
        if self.key not in ENUM_OPTIONS:
            return None
        options = list(ENUM_OPTIONS.get(self.key, ()))
        current = self.native_value
        if current and current not in options:
            options.append(current)
        return options or None
