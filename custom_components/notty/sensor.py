from __future__ import annotations

from datetime import UTC, datetime
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from custom_components.notty.api import JsonValue, matches_value
from custom_components.notty.binary_sensor import BINARY_KEYS, looks_boolean_key
from custom_components.notty.coordinator import NOTTY_SERVER_TIME_ZONE, NottyCoordinator
from custom_components.notty.entity import NottyEntity, merged_device_data, title_from_key, value_from_block
from custom_components.notty.models import DeviceBlock, DeviceData, NottyConfigEntry

DECIMAL_SEPARATOR = "."
FIELD_SEX = "sex"
DATETIME_FIELD_FRAGMENT = "datetime"
FIELD_EVENTS = "events"
FIELD_DEVICE_TIME_ZONE = "time_zone_iana"

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

WEIGHT_KEYS = {"today_weight", "yesterday_weight", "total_weight", "weight"}
POUNDS_TO_KILOGRAMS = 0.45359237
WEIGHT_UNIT_FACTORS: dict[str | None, float] = {"kg": 1.0, "lb": POUNDS_TO_KILOGRAMS}
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
    "latest_event_event_type_id": tuple(f"event_type_{value}" for value in range(30)),
    "upgrade_task_status": tuple(f"task_status_{value}" for value in range(10)),
}
ENUM_VALUE_PREFIX = {"lb_mode": "mode", "lb_status": "status"}


def timezone_context(value: JsonValue, ha_zone: str, *, at: datetime | None = None) -> DeviceData:
    """Report device/HA zone offsets without conflating them with API clocks.

    Returns:
        Read-only timezone diagnostics. Missing/invalid IANA names never
        become guessed device zones.
    """
    context: DeviceData = {
        "source": "notty_device",
        "home_assistant_time_zone": ha_zone,
        "server_clock_assumption": NOTTY_SERVER_TIME_ZONE,
        "device_iana_valid": False,
    }
    if not isinstance(value, str) or not value:
        return context
    try:
        device_tz = ZoneInfo(value)
        home_tz = ZoneInfo(ha_zone)
    except KeyError, ValueError, ZoneInfoNotFoundError:
        return context
    now = at or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        return context
    device_offset = now.astimezone(device_tz).utcoffset()
    ha_offset = now.astimezone(home_tz).utcoffset()
    if device_offset is None or ha_offset is None:
        return context
    device_minutes = int(device_offset.total_seconds() // 60)
    ha_minutes = int(ha_offset.total_seconds() // 60)
    context.update({
        "device_iana_valid": True,
        "device_utc_offset_minutes": device_minutes,
        "home_assistant_utc_offset_minutes": ha_minutes,
        "device_minus_ha_offset_minutes": device_minutes - ha_minutes,
    })
    return context


def _is_scalar(value: JsonValue) -> bool:
    return value is not None and not isinstance(value, (dict, list, set, tuple))


def _valid_sensor_value(value: JsonValue) -> bool:
    return not isinstance(value, str) or len(value) <= MAX_STATE_LENGTH


def sensor_keys(block: DeviceBlock) -> list[str]:
    """Sensor keys.

    Returns:
        list[str]: The resulting sensor keys.
    """
    merged = merged_device_data(block)
    keys = []
    for key, value in merged.items():
        if (
            key in SKIP_KEYS
            or key in BINARY_KEYS
            or key.endswith("_str")
            or key.startswith(NON_LITTER_PREFIXES)
            or isinstance(value, bool)
        ):
            continue
        if not _is_scalar(value) or not _valid_sensor_value(value) or looks_boolean_key(key, value):
            continue
        keys.append(key)
    return sorted(keys)


def _number_or_original(value: JsonValue) -> JsonValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped) if DECIMAL_SEPARATOR in stripped else int(stripped)
        except ValueError:
            return value
    return value


def _is_numeric_value(value: JsonValue) -> bool:
    return isinstance(_number_or_original(value), (int, float)) and not isinstance(value, bool)


def _parse_timestamp_value(value: object) -> datetime | None:
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


def _enum_value(key: str, value: JsonValue) -> str | None:
    if matches_value(value, (None, "")):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            value = int(stripped)
    if key == FIELD_SEX:
        return ENUM_LABELS["sex"].get(value, f"Sex {value}") if isinstance(value, int) else f"Sex {value}"
    if key in ENUM_LABELS:
        return (
            ENUM_LABELS[key].get(value, f"{title_from_key(key)} {value}")
            if isinstance(value, int)
            else f"{title_from_key(key)} {value}"
        )
    prefix = ENUM_VALUE_PREFIX.get(key, key)
    return f"{prefix}_{value}"


def sensor_metadata(
    key: str, raw_value: JsonValue
) -> tuple[SensorDeviceClass | None, str | None, SensorStateClass | None]:
    """Sensor metadata.

    Returns:
        tuple[SensorDeviceClass | None, str | None, SensorStateClass | None]: The resulting sensor metadata.
    """
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


async def async_setup_entry(  # ruff: ignore[unused-async] -- Home Assistant requires an async callback.
    _hass: HomeAssistant, entry: NottyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Async setup entry."""
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    def discover() -> None:
        """Discover recovered optional fields without duplicating existing entities."""
        entities: list[NottySensor] = []
        for device_id, block in coordinator.data.items():
            keys = set(sensor_keys(block))
            keys.update((WEIGHT_KEYS - SKIP_KEYS).intersection(merged_device_data(block)))
            for key in sorted(keys):
                if (device_id, key) not in known:
                    entities.append(NottySensor(coordinator, device_id, block["device"], key))
                    known.add((device_id, key))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class NottySensor(NottyEntity, SensorEntity):
    def __init__(self, coordinator: NottyCoordinator, device_id: str, device: DeviceData, key: str) -> None:
        super().__init__(coordinator, device_id, device)
        self.key = key
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_name = title_from_key(key)
        if key == FIELD_DEVICE_TIME_ZONE:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        raw_value = value_from_block(self.block, self.key)
        device_class, unit, state_class = sensor_metadata(key, raw_value)
        if key in WEIGHT_KEYS:
            device_class, unit, state_class = (
                SensorDeviceClass.WEIGHT,
                UnitOfMass.KILOGRAMS,
                SensorStateClass.MEASUREMENT,
            )
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        if state_class is not None:
            self._attr_state_class = state_class

    @property
    def native_value(self) -> StateType | datetime:
        """Native value.

        Returns:
            StateType | datetime: The resulting native value.
        """
        raw_value = value_from_block(self.block, self.key)
        if self.key in WEIGHT_KEYS:
            return self._weight_in_kilograms(raw_value)
        timestamp_value = _parse_timestamp_value(raw_value)
        if timestamp_value is not None and (
            DATETIME_FIELD_FRAGMENT in self.key or self.key in {"latest_message_date_created", "messages_date_created"}
        ):
            return timestamp_value
        if self.key in ENUM_OPTIONS:
            return _enum_value(self.key, raw_value)
        value = _number_or_original(raw_value)
        return value if isinstance(value, (str, int, float)) else None

    def _weight_in_kilograms(self, raw_value: JsonValue) -> float | None:
        value = _number_or_original(raw_value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            finite = math.isfinite(value)
        except OverflowError:
            return None
        if not finite or value <= 0:
            return None
        unit = self._reported_weight_unit()
        factor = WEIGHT_UNIT_FACTORS.get(unit)
        return float(value) * factor if factor is not None else None

    def _reported_weight_unit(self) -> str | None:
        raw = value_from_block(self.block, "weight_unit")
        return None if isinstance(raw, bool | float) else _enum_value("weight_unit", raw)

    @property
    def extra_state_attributes(self) -> DeviceData | None:
        """Extra state attributes.

        Returns:
            DeviceData | None: The resulting extra state attributes.
        """
        attributes: DeviceData = {}
        if self.key in WEIGHT_KEYS:
            attributes.update({
                "source_field": self.key,
                "reported_unit": self._reported_weight_unit(),
                "measurement_time": None,
                "measurement_freshness": "not_reported",
                "measurement_source": "cloud_daily_summary"
                if self.key in {"today_weight", "yesterday_weight"}
                else "cloud_reported_weight",
            })
        if self.key == FIELD_DEVICE_TIME_ZONE:
            attributes.update(
                timezone_context(value_from_block(self.block, self.key), self.coordinator.hass.config.time_zone)
            )
        if self.key in ENUM_OPTIONS:
            attributes["raw_value"] = value_from_block(self.block, self.key)
        source_key = RELATED_ATTRIBUTE_KEYS.get(self.key)
        if source_key:
            if source_key == FIELD_EVENTS:
                value = self.block.get("info", {}).get("events")
            else:
                related = self.block["info"].get("_notty_related")
                value = related.get(source_key) if isinstance(related, dict) else None
            if value:
                attributes[source_key] = value
        return attributes or None

    @property
    def options(self) -> list[str] | None:
        """Options.

        Returns:
            list[str] | None: The resulting options.
        """
        if self.key not in ENUM_OPTIONS:
            return None
        options = list(ENUM_OPTIONS.get(self.key, ()))
        current = self.native_value
        if isinstance(current, str) and current and current not in options:
            options.append(current)
        return options or None
