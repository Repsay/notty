from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import operator
import re
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from custom_components.notty.api import JsonObject, JsonValue, NottyApi, NottyApiError, NottyAuthError, matches_value
from custom_components.notty.const import (
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from custom_components.notty.models import CoordinatorData, DeviceData, NottyConfigEntry

TOILET_EVENT_TYPE_ID = 12
TOILET_EVENT_WORD = "spent"
LITTER_BOX_EVENT_WORD = "litter box"
PET_EVENT_SEPARATOR = " just spent "
LITTER_DEVICE_WORD = "litter"
SAND_DEVICE_WORD = "sand"
DECIMAL_SEPARATOR = "."
MAX_FLATTEN_DEPTH = 2
FIELD_UPGRADE = "upgrade"
FIELD_MESSAGES = "messages"
FIELD_ASSOCIATED_USERS = "associated_users"
FIELD_PLANS = "plans"
FIELD_PET_DATA_LIST = "pet_data_list"
FIELD_DAILY_EVENT_COUNTS = "daily_event_counts"
FIELD_ASSOCIATED_PETS = "associated_pets"
DEVICE_TYPE_LITTER_BOX = "litter_box"
SOURCE_PET = "pet"

_LOGGER = logging.getLogger(__name__)
NOTTY_SERVER_TIME_ZONE = "Asia/Shanghai"

LIST_KEYS = ("list", "devices", "rows", "items", "data")
PET_ID_KEYS = ("pet_id", "petId", "id")
PET_NAME_KEYS = ("alias", "name", "pet_name", "petName")
SCALAR_TYPES = (str, int, float, bool)
SKIP_FLATTEN_KEYS = {"access_token", "health_url", "image_path", "image_url", "token"}
NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?")
TOILET_DURATION_RE = re.compile(
    r"\bspent\s+(?:(?P<minutes>\d+)m(?:\s+(?P<seconds>\d+)s)?|(?P<only_seconds>\d+)s)\b", re.IGNORECASE
)


def _timezone(name: str | None, fallback: str = "UTC") -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except ZoneInfoNotFoundError:
        return ZoneInfo(fallback)


def _parse_notty_datetime(date_value: JsonValue, time_value: JsonValue = None) -> datetime | None:
    if matches_value(date_value, (None, "")):
        return None
    text = str(date_value).strip()
    if not matches_value(time_value, (None, "")):
        text = f"{text} {str(time_value).strip()}"
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(f"{text} +0000", f"{date_format} %z")
        except ValueError:
            _LOGGER.debug("Device timestamp did not match date format %s", date_format)
    return None


def format_local_datetime(
    date_value: JsonValue,
    time_value: JsonValue,
    target_time_zone: str | None,
    *,
    source_time_zone: str = NOTTY_SERVER_TIME_ZONE,
) -> tuple[str, str, str] | None:
    """Format local datetime.

    Returns:
        tuple[str, str, str] | None: The resulting format local datetime.
    """
    parsed = _parse_notty_datetime(date_value, time_value)
    if parsed is None:
        return None
    local = parsed.replace(tzinfo=_timezone(source_time_zone)).astimezone(_timezone(target_time_zone))
    return (local.strftime("%Y-%m-%d"), local.strftime("%H:%M"), local.isoformat(timespec="minutes"))


def _is_toilet_event(event: JsonObject) -> bool:
    if event.get("event_type_id") == TOILET_EVENT_TYPE_ID:
        return True
    text = str(event.get("event") or "").lower()
    return TOILET_EVENT_WORD in text and LITTER_BOX_EVENT_WORD in text


def toilet_event_summary(event: JsonObject, target_time_zone: str | None) -> JsonObject:
    """Toilet event summary.

    Returns:
        JsonObject: The resulting toilet event summary.
    """
    summary: JsonObject = {
        "latest_toilet_event": event.get("event"),
        "latest_toilet_event_raw_date": event.get("date"),
        "latest_toilet_event_raw_time": event.get("time"),
    }
    local_event = format_local_datetime(event.get("date"), event.get("time"), target_time_zone)
    if local_event:
        local_date, local_time, iso_value = local_event
        summary["latest_toilet_event_date"] = local_date
        summary["latest_toilet_event_time"] = local_time
        summary["latest_toilet_event_datetime"] = iso_value

    text = str(event.get("event") or "")
    if PET_EVENT_SEPARATOR in text:
        summary["latest_toilet_event_pet_name"] = text.split(" just spent ", 1)[0]
    duration_match = TOILET_DURATION_RE.search(text)
    if duration_match:
        minutes = int(duration_match.group("minutes") or 0)
        seconds = int(duration_match.group("seconds") or duration_match.group("only_seconds") or 0)
        summary["latest_toilet_event_duration"] = minutes * 60 + seconds
    return {key: value for key, value in summary.items() if not matches_value(value, (None, ""))}


def _device_id(device: DeviceData) -> str:
    return str(device.get("user_device_id") or device.get("device_id") or device.get("id") or device.get("did") or "")


def _device_type(device: DeviceData) -> str | None:
    raw_type = " ".join(
        str(device.get(key) or "")
        for key in ("device_type", "type", "category", "alias", "name", "device_name", "product_name", "model")
    ).lower()
    if LITTER_DEVICE_WORD in raw_type or SAND_DEVICE_WORD in raw_type or device.get("has_litter_box_data"):
        return "litter_box"
    return None


def _is_scalar(value: JsonValue) -> bool:
    return value is None or isinstance(value, SCALAR_TYPES)


def _as_list(value: JsonValue) -> list[JsonObject]:
    if isinstance(value, dict):
        for key in LIST_KEYS:
            items = value.get(key)
            if isinstance(items, list):
                value = items
                break
        else:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_value(data: JsonObject, keys: tuple[str, ...]) -> JsonValue:
    for key in keys:
        value = data.get(key)
        if not matches_value(value, (None, "")):
            return value
    return None


def _slug(value: JsonValue) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return text or "unknown"


def _number_from_text(value: str) -> int | float | None:
    match = NUMBER_RE.match(value.strip())
    if not match:
        return None
    number = match.group(0)
    try:
        return float(number) if DECIMAL_SEPARATOR in number else int(number)
    except ValueError:
        return None


def _numeric_values(values: list[JsonValue]) -> list[int | float]:
    return [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]


def merge_chart_summary(target: JsonObject, out_key: str, value: JsonObject) -> None:
    """Merge chart summary."""
    values = value.get("values")
    if not isinstance(values, list):
        return
    numbers = _numeric_values(values)
    if not numbers:
        return
    target[f"{out_key}_total"] = sum(numbers)
    target[f"{out_key}_max"] = max(numbers)
    target[f"{out_key}_nonzero_count"] = len([item for item in numbers if item])
    target[f"{out_key}_latest"] = numbers[-1]
    times = value.get("times")
    if isinstance(times, list) and times:
        target[f"{out_key}_latest_time"] = times[min(len(times), len(values)) - 1]
        for index in range(len(values) - 1, -1, -1):
            if isinstance(values[index], (int, float)) and values[index]:
                target[f"{out_key}_latest_nonzero"] = values[index]
                if index < len(times):
                    target[f"{out_key}_latest_nonzero_time"] = times[index]
                break


def _pet_id(data: JsonObject) -> str | None:
    value = _first_value(data, PET_ID_KEYS)
    return str(value) if not matches_value(value, (None, "")) else None


def _pet_name(data: JsonObject) -> str | None:
    value = _first_value(data, PET_NAME_KEYS)
    return str(value) if not matches_value(value, (None, "")) else None


def _merge_scalar_fields(target: JsonObject, source: JsonObject, *, prefix: str = "", depth: int = 0) -> None:
    for source_key, value in source.items():
        key = str(source_key)
        if key in SKIP_FLATTEN_KEYS or key.startswith("_"):
            continue
        out_key = f"{prefix}{key}"
        if _is_scalar(value):
            if not matches_value(value, (None, "")):
                target[out_key] = value
                if isinstance(value, str) and key.endswith("_str"):
                    number = _number_from_text(value)
                    if number is not None:
                        target.setdefault(f"{prefix}{key.removesuffix('_str')}", number)
        elif isinstance(value, dict) and depth < MAX_FLATTEN_DEPTH:
            merge_chart_summary(target, out_key, value)
            _merge_scalar_fields(target, value, prefix=f"{out_key}_", depth=depth + 1)
        elif isinstance(value, list):
            target[f"{out_key}_count"] = len(value)
            if value and isinstance(value[-1], dict) and depth < MAX_FLATTEN_DEPTH:
                _merge_scalar_fields(target, value[-1], prefix=f"latest_{out_key}_", depth=depth + 1)


def _related_summary(related: JsonObject, *, unprefixed: set[str] | None = None) -> JsonObject:
    unprefixed = unprefixed or set()
    summary: JsonObject = {}
    for key, value in related.items():
        if key.endswith("_count"):
            summary[key] = value
        elif isinstance(value, list):
            summary[f"{key}_count"] = len(value)
        elif isinstance(value, dict):
            prefix = "" if key in unprefixed else f"{key}_"
            _merge_scalar_fields(summary, value, prefix=prefix)
            rows = _as_list(value)
            if rows:
                summary[f"{key}_count"] = len(rows)
    return summary


def _calendar_event_summary(values: list[JsonValue], local_today: date) -> JsonObject:
    summary: JsonObject = {}
    dated_counts: list[tuple[date, int]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        count = item.get("count")
        if isinstance(count, bool) or not isinstance(count, int):
            continue
        try:
            event_day = date(int(str(item["year"])), int(str(item["month"])), int(str(item["day"])))
        except KeyError, ValueError, TypeError:
            _LOGGER.debug("Ignoring an event count with an invalid calendar date")
        else:
            if event_day <= local_today:
                dated_counts.append((event_day, count))
    if dated_counts:
        latest_day, latest_count = max(dated_counts, key=operator.itemgetter(0))
        total = sum(count for _, count in dated_counts)
        summary.update({
            "latest_daily_event_date": latest_day.isoformat(),
            "latest_daily_event_count": latest_count,
            "daily_events_total": total,
            "daily_events_last_7_days": sum(
                count for day, count in dated_counts if local_today - timedelta(days=6) <= day <= local_today
            ),
            "daily_events_last_30_days": sum(
                count for day, count in dated_counts if local_today - timedelta(days=29) <= day <= local_today
            ),
            "daily_events_average": round(total / len(dated_counts), 2),
        })
    return summary


def _message_summary(value: JsonObject, target_time_zone: str | None) -> JsonObject:
    summary = {
        f"latest_message_{field}": value[field]
        for field in ("title", "sub_title", "date_created")
        if not matches_value(value.get(field), (None, ""))
    }
    local = format_local_datetime(
        value.get("date_created_utc") or value.get("date_created"),
        None,
        target_time_zone,
        source_time_zone="UTC" if value.get("date_created_utc") else NOTTY_SERVER_TIME_ZONE,
    )
    if local:
        summary.update({
            "messages_date_created_raw": value.get("date_created"),
            "messages_date_created": local[2],
            "latest_message_date_created_raw": value.get("date_created"),
            "latest_message_date_created": local[2],
        })
    return summary


def _related_object_summary(key: str, value: JsonObject, target_time_zone: str | None) -> JsonObject:
    if key == FIELD_UPGRADE:
        return {
            f"upgrade_{field}": value[field]
            for field in ("src_version", "dest_version", "task_status")
            if not matches_value(value.get(field), (None, ""))
        }
    if key == FIELD_MESSAGES:
        return _message_summary(value, target_time_zone)
    shareds = value.get("shareds")
    if key == FIELD_ASSOCIATED_USERS and isinstance(shareds, list):
        return {"associated_shared_user_count": len(shareds)}
    return {}


def _related_list_summary(key: str, value: list[JsonValue], local_today: date) -> JsonObject:
    summary: JsonObject = {f"{key}_count": len(value)}
    rows = [item for item in value if isinstance(item, dict)]
    if key == FIELD_PLANS:
        summary["enabled_plans_count"] = sum(bool(item.get("open")) for item in rows)
        times = [str(item["time"]) for item in rows if item.get("time")]
        if times:
            summary["plan_times"] = ", ".join(times)
    elif key == FIELD_DAILY_EVENT_COUNTS:
        summary.update(_calendar_event_summary(value, local_today))
    elif key in {FIELD_PET_DATA_LIST, FIELD_ASSOCIATED_PETS}:
        names = [
            str(item["name"])
            for item in rows
            if item.get("name") and (key != FIELD_ASSOCIATED_PETS or item.get("is_associated"))
        ]
        if names:
            summary["litter_pet_names" if key == FIELD_PET_DATA_LIST else "associated_pet_names"] = ", ".join(names)
    return summary


def litter_related_summary(
    related: DeviceData, target_time_zone: str | None = None, *, today: date | None = None
) -> DeviceData:
    """Summarize optional device endpoints using the local calendar date.

    Returns:
        Scalar attributes derived from the supported response shapes.
    """
    summary = _related_summary(related)
    local_today = today or datetime.now(_timezone(target_time_zone)).date()
    for key, value in related.items():
        if key.endswith("_count"):
            summary[key] = value
        elif isinstance(value, dict):
            summary.update(_related_object_summary(key, value, target_time_zone))
        elif isinstance(value, list):
            summary.update(_related_list_summary(key, value, local_today))
    return summary


def _pet_related_summary(related: JsonObject) -> JsonObject:
    return _related_summary(related, unprefixed={"info"})


def _pet_device_from_row(parent_device: JsonObject, parent_did: str, row: JsonObject) -> tuple[str, JsonObject] | None:
    pet_id = _pet_id(row)
    pet_name = _pet_name(row)
    if not pet_id and not pet_name:
        return None
    stable_id = pet_id or f"{parent_did}_{_slug(pet_name)}"
    device_id = f"pet_{stable_id}"
    device = {
        **row,
        "_notty_source": "pet",
        "_notty_has_device_id": False,
        "_notty_litter_user_device_id": parent_did,
        "device_type": "litter_box",
        "product_name": "Cat Automatic Litter Box",
        "model": "Litter Box Pet",
        "id": device_id,
        "pet_id": pet_id or stable_id,
        "alias": pet_name or f"Pet {stable_id}",
    }
    if parent_device.get("_notty_pet_ids"):
        device["_notty_pet_ids"] = parent_device["_notty_pet_ids"]
    return device_id, device


def _extract_pet_rows(value: JsonValue) -> list[JsonObject]:
    rows = _as_list(value)
    if rows:
        return rows
    if isinstance(value, dict) and (_pet_id(value) or _pet_name(value)):
        return [value]
    return []


def _merge_block(
    blocks: CoordinatorData, device_id: str, device: JsonObject, info: JsonObject, device_type: str
) -> None:
    existing = blocks.get(device_id, {"device": {}, "info": {}, "type": device_type})
    merged_device = {**existing.get("device", {}), **device}
    merged_info = {**existing.get("info", {}), **info}
    # Account discovery can contain a null parent even when the physical box
    # has already supplied an associated-pet row with a valid parent.
    for merged, previous, key in (
        (merged_device, existing.get("device", {}), "_notty_litter_user_device_id"),
        (merged_info, existing.get("info", {}), "litter_user_device_id"),
    ):
        if not merged.get(key) and previous.get(key):
            merged[key] = previous[key]
    blocks[device_id] = {"device": merged_device, "info": merged_info, "type": device_type}


def _merge_related_pet_blocks(
    blocks: CoordinatorData, parent_device: JsonObject, parent_did: str, related: JsonObject
) -> None:
    for source_key in ("pet_data_list", "pet_data_statistics", "pet_data_detail", "associated_pets"):
        for row in _extract_pet_rows(related.get(source_key)):
            pet = _pet_device_from_row(parent_device, parent_did, row)
            if not pet:
                continue
            device_id, device = pet
            info: JsonObject = {"litter_user_device_id": parent_did, "source_endpoint": source_key}
            _merge_scalar_fields(info, row)
            _merge_block(blocks, device_id, device, info, "litter_box")


def litter_info_summary(info: DeviceData, target_time_zone: str | None = None) -> DeviceData:
    """Litter info summary.

    Returns:
        DeviceData: The resulting litter info summary.
    """
    events = info.get("events")
    summary: JsonObject = {}
    if info.get("status_id") is not None:
        summary["is_online"] = info.get("status_id") == 1
    if not isinstance(events, list):
        return summary
    summary["events_count"] = len(events)
    if events and isinstance(events[0], dict):
        latest = events[0]
        for field in ("event", "event_type_id", "date", "time"):
            if not matches_value(latest.get(field), (None, "")):
                summary[f"latest_event_{field}"] = latest[field]
        local_event = format_local_datetime(latest.get("date"), latest.get("time"), target_time_zone)
        if local_event:
            local_date, local_time, iso_value = local_event
            summary["latest_event_raw_date"] = latest.get("date")
            summary["latest_event_raw_time"] = latest.get("time")
            summary["latest_event_date"] = local_date
            summary["latest_event_time"] = local_time
            summary["latest_event_datetime"] = iso_value
    for event in events:
        if isinstance(event, dict) and _is_toilet_event(event):
            summary.update(toilet_event_summary(event, target_time_zone))
            break
    return summary


class NottyCoordinator(DataUpdateCoordinator[CoordinatorData]):
    def __init__(self, hass: HomeAssistant, api: NottyApi, entry: NottyConfigEntry | None = None) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            always_update=False,
            config_entry=entry,
        )
        self.api = api
        self._entry = entry
        self.entry_id = entry.entry_id if entry is not None else None

    async def _async_update_data(self) -> CoordinatorData:
        try:
            result = await self._collect_data()
        except NottyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NottyApiError as err:
            raise UpdateFailed(str(err)) from err
        else:
            return result

    async def _collect_data(self) -> CoordinatorData:
        devices = await self.api.devices()
        out: CoordinatorData = {}
        for device in devices:
            did = _device_id(device)
            if not did:
                continue

            device_type = _device_type(device)
            if device_type != DEVICE_TYPE_LITTER_BOX:
                _LOGGER.debug("Skipping non-litter-box NOTTY device payload: %s", device)
                continue

            if device.get("_notty_source") == SOURCE_PET:
                info = await self._pet_info(device)
            else:
                info = await self.api.device_info(did, device_type)
                if device_type == DEVICE_TYPE_LITTER_BOX:
                    target_time_zone = str(
                        info.get("time_zone_iana") or device.get("time_zone_iana") or self.hass.config.time_zone
                    )
                    related = await self.api.litter_related_info(did)
                    info = {
                        **info,
                        **litter_info_summary(info, target_time_zone),
                        **litter_related_summary(related, target_time_zone),
                        "_notty_related": related,
                    }
                    unread_count = await self.api.unread_message_count()
                    if unread_count is not None:
                        info["unread_message_count"] = unread_count
                    _merge_related_pet_blocks(out, device, did, related)
            if not info:
                _LOGGER.debug("Skipping NOTTY litter box without bound info payload: %s", device)
                continue
            _merge_block(out, did, device, info, device_type)
        if self._entry is not None:
            previous_data = cast("JsonObject", self._entry.data)
            data = dict(previous_data)
            data.update({
                key: value
                for key, value in (
                    (CONF_ACCESS_TOKEN, self.api.token),
                    (CONF_REFRESH_TOKEN, self.api.refresh_token),
                    (CONF_USER_ID, self.api.user_id),
                )
                if value
            })
            if data != previous_data:
                self.hass.config_entries.async_update_entry(self._entry, data=data)
        return out

    async def _pet_info(self, device: JsonObject) -> JsonObject:
        pet_id = str(device.get("pet_id") or "").removeprefix("pet_")
        related = await self.api.pet_related_info(pet_id) if pet_id else {}
        info = {
            **device,
            **_pet_related_summary(related),
            "litter_user_device_id": device.get("_notty_litter_user_device_id"),
            "_notty_related": related,
        }
        _merge_scalar_fields(info, device)
        related_info = related.get("info")
        if isinstance(related_info, dict):
            pet_devices = related_info.get("pet_devices")
            if isinstance(pet_devices, list):
                # Keep the raw binding list for safe pet-weight writes.
                info["pet_devices"] = pet_devices
                linked_id = NottyApi.pet_litter_device_id({"pet_devices": pet_devices})
                if linked_id:
                    device["_notty_litter_user_device_id"] = linked_id
                    info["litter_user_device_id"] = linked_id
        return info
