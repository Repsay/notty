import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NottyApi, NottyApiError, NottyAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_USER_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
NOTTY_SERVER_TIME_ZONE = "Asia/Shanghai"

LIST_KEYS = ("list", "devices", "rows", "items", "data")
PET_ID_KEYS = ("pet_id", "petId", "id")
PET_NAME_KEYS = ("alias", "name", "pet_name", "petName")
SCALAR_TYPES = (str, int, float, bool)
SKIP_FLATTEN_KEYS = {
    "access_token",
    "health_url",
    "image_path",
    "image_url",
    "token",
}
NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?")
TOILET_DURATION_RE = re.compile(r"\bspent\s+(\d+)s\b", re.IGNORECASE)


def _timezone(name: str | None, fallback: str = "UTC") -> ZoneInfo:
    try:
        return ZoneInfo(name or fallback)
    except ZoneInfoNotFoundError:
        return ZoneInfo(fallback)


def _parse_notty_datetime(date_value: Any, time_value: Any = None) -> datetime | None:
    if date_value in (None, ""):
        return None
    text = str(date_value).strip()
    if time_value not in (None, ""):
        text = f"{text} {str(time_value).strip()}"
    for date_format in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _format_local_datetime(
    date_value: Any,
    time_value: Any,
    target_time_zone: str | None,
    *,
    source_time_zone: str = NOTTY_SERVER_TIME_ZONE,
) -> tuple[str, str, str] | None:
    parsed = _parse_notty_datetime(date_value, time_value)
    if parsed is None:
        return None
    local = parsed.replace(tzinfo=_timezone(source_time_zone)).astimezone(
        _timezone(target_time_zone)
    )
    return (
        local.strftime("%Y-%m-%d"),
        local.strftime("%H:%M"),
        local.isoformat(timespec="minutes"),
    )


def _is_toilet_event(event: dict[str, Any]) -> bool:
    if event.get("event_type_id") == 12:
        return True
    text = str(event.get("event") or "").lower()
    return "spent" in text and "litter box" in text


def _toilet_event_summary(
    event: dict[str, Any],
    target_time_zone: str | None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "latest_toilet_event": event.get("event"),
        "latest_toilet_event_raw_date": event.get("date"),
        "latest_toilet_event_raw_time": event.get("time"),
    }
    local_event = _format_local_datetime(
        event.get("date"),
        event.get("time"),
        target_time_zone,
    )
    if local_event:
        local_date, local_time, iso_value = local_event
        summary["latest_toilet_event_date"] = local_date
        summary["latest_toilet_event_time"] = local_time
        summary["latest_toilet_event_datetime"] = iso_value

    text = str(event.get("event") or "")
    if " just spent " in text:
        summary["latest_toilet_event_pet_name"] = text.split(" just spent ", 1)[0]
    duration_match = TOILET_DURATION_RE.search(text)
    if duration_match:
        summary["latest_toilet_event_duration"] = int(duration_match.group(1))
    return {key: value for key, value in summary.items() if value not in (None, "")}


def _device_id(device: dict) -> str:
    return str(
        device.get("user_device_id")
        or device.get("device_id")
        or device.get("id")
        or device.get("did")
        or ""
    )


def _device_type(device: dict) -> str | None:
    raw_type = " ".join(
        str(device.get(key) or "")
        for key in (
            "device_type",
            "type",
            "category",
            "alias",
            "name",
            "device_name",
            "product_name",
            "model",
        )
    ).lower()
    if "litter" in raw_type or "sand" in raw_type or device.get("has_litter_box_data"):
        return "litter_box"
    return None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, SCALAR_TYPES)


def _as_list(value: Any) -> list[dict[str, Any]]:
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


def _first_value(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return text or "unknown"


def _number_from_text(value: str) -> int | float | None:
    match = NUMBER_RE.match(value.strip())
    if not match:
        return None
    number = match.group(0)
    try:
        return float(number) if "." in number else int(number)
    except ValueError:
        return None


def _numeric_values(values: list[Any]) -> list[int | float]:
    return [
        value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]


def _merge_chart_summary(target: dict[str, Any], out_key: str, value: dict[str, Any]) -> None:
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


def _pet_id(data: dict[str, Any]) -> str | None:
    value = _first_value(data, PET_ID_KEYS)
    return str(value) if value not in (None, "") else None


def _pet_name(data: dict[str, Any]) -> str | None:
    value = _first_value(data, PET_NAME_KEYS)
    return str(value) if value not in (None, "") else None


def _merge_scalar_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    *,
    prefix: str = "",
    depth: int = 0,
) -> None:
    for key, value in source.items():
        key = str(key)
        if key in SKIP_FLATTEN_KEYS or key.startswith("_"):
            continue
        out_key = f"{prefix}{key}"
        if _is_scalar(value):
            if value not in (None, ""):
                target[out_key] = value
                if isinstance(value, str) and key.endswith("_str"):
                    number = _number_from_text(value)
                    if number is not None:
                        target.setdefault(f"{prefix}{key.removesuffix('_str')}", number)
        elif isinstance(value, dict) and depth < 2:
            _merge_chart_summary(target, out_key, value)
            _merge_scalar_fields(target, value, prefix=f"{out_key}_", depth=depth + 1)
        elif isinstance(value, list):
            target[f"{out_key}_count"] = len(value)
            if value and isinstance(value[-1], dict) and depth < 2:
                _merge_scalar_fields(
                    target, value[-1], prefix=f"latest_{out_key}_", depth=depth + 1
                )


def _related_summary(
    related: dict[str, Any], *, unprefixed: set[str] | None = None
) -> dict[str, Any]:
    unprefixed = unprefixed or set()
    summary: dict[str, Any] = {}
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


def _litter_related_summary(
    related: dict, target_time_zone: str | None = None, *, today: date | None = None
) -> dict:
    summary = _related_summary(related)
    for key, value in related.items():
        if key.endswith("_count"):
            summary[f"{key}"] = value
        elif key == "upgrade" and isinstance(value, dict):
            for field in ("src_version", "dest_version", "task_status"):
                if value.get(field) not in (None, ""):
                    summary[f"upgrade_{field}"] = value[field]
        elif key == "messages" and isinstance(value, dict):
            for field in ("title", "sub_title", "date_created"):
                if value.get(field) not in (None, ""):
                    summary[f"latest_message_{field}"] = value[field]
            message_date_value = value.get("date_created_utc") or value.get("date_created")
            local_message = _format_local_datetime(
                message_date_value,
                None,
                target_time_zone,
                source_time_zone="UTC" if value.get("date_created_utc") else NOTTY_SERVER_TIME_ZONE,
            )
            if local_message:
                _date, _time, iso_value = local_message
                summary["messages_date_created_raw"] = value.get("date_created")
                summary["messages_date_created"] = iso_value
                summary["latest_message_date_created_raw"] = value.get("date_created")
                summary["latest_message_date_created"] = iso_value
        elif key == "associated_users" and isinstance(value, dict):
            shareds = value.get("shareds")
            if isinstance(shareds, list):
                summary["associated_shared_user_count"] = len(shareds)
        elif isinstance(value, list):
            summary[f"{key}_count"] = len(value)
            if key == "plans":
                summary["enabled_plans_count"] = len([item for item in value if item.get("open")])
                times = [str(item.get("time")) for item in value if item.get("time")]
                if times:
                    summary["plan_times"] = ", ".join(times)
            elif key == "pet_data_list":
                names = [str(item.get("name")) for item in value if item.get("name")]
                if names:
                    summary["litter_pet_names"] = ", ".join(names)
            elif key == "daily_event_counts" and value:
                local_today = today or datetime.now(_timezone(target_time_zone)).date()
                dated_counts: list[tuple[date, int]] = []
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    count = item.get("count")
                    if isinstance(count, bool) or not isinstance(count, int):
                        continue
                    try:
                        event_day = date(int(item["year"]), int(item["month"]), int(item["day"]))
                    except KeyError, ValueError, TypeError:
                        continue
                    if event_day <= local_today:
                        dated_counts.append((event_day, count))
                if dated_counts:
                    latest_day, latest_count = max(dated_counts, key=lambda row: row[0])
                    summary["latest_daily_event_date"] = latest_day.isoformat()
                    summary["latest_daily_event_count"] = latest_count
                    summary["daily_events_total"] = sum(count for _, count in dated_counts)
                    summary["daily_events_last_7_days"] = sum(
                        count
                        for day, count in dated_counts
                        if local_today - timedelta(days=6) <= day <= local_today
                    )
                    summary["daily_events_last_30_days"] = sum(
                        count
                        for day, count in dated_counts
                        if local_today - timedelta(days=29) <= day <= local_today
                    )
                    summary["daily_events_average"] = round(
                        summary["daily_events_total"] / len(dated_counts), 2
                    )
            elif key == "associated_pets":
                names = [
                    str(item.get("name"))
                    for item in value
                    if item.get("is_associated") and item.get("name")
                ]
                if names:
                    summary["associated_pet_names"] = ", ".join(names)
    return summary


def _pet_related_summary(related: dict[str, Any]) -> dict[str, Any]:
    return _related_summary(related, unprefixed={"info"})


def _pet_device_from_row(
    parent_device: dict[str, Any], parent_did: str, row: dict[str, Any]
) -> tuple[str, dict[str, Any]] | None:
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


def _extract_pet_rows(value: Any) -> list[dict[str, Any]]:
    rows = _as_list(value)
    if rows:
        return rows
    if isinstance(value, dict) and (_pet_id(value) or _pet_name(value)):
        return [value]
    return []


def _merge_block(
    blocks: dict[str, dict[str, Any]],
    device_id: str,
    device: dict[str, Any],
    info: dict[str, Any],
    device_type: str,
) -> None:
    existing = blocks.get(device_id, {})
    blocks[device_id] = {
        "device": {**existing.get("device", {}), **device},
        "info": {**existing.get("info", {}), **info},
        "type": device_type,
    }


def _merge_related_pet_blocks(
    blocks: dict[str, dict[str, Any]],
    parent_device: dict[str, Any],
    parent_did: str,
    related: dict[str, Any],
) -> None:
    for source_key in (
        "pet_data_list",
        "pet_data_statistics",
        "pet_data_detail",
        "associated_pets",
    ):
        for row in _extract_pet_rows(related.get(source_key)):
            pet = _pet_device_from_row(parent_device, parent_did, row)
            if not pet:
                continue
            device_id, device = pet
            info = {
                "litter_user_device_id": parent_did,
                "source_endpoint": source_key,
            }
            _merge_scalar_fields(info, row)
            _merge_block(blocks, device_id, device, info, "litter_box")


def _litter_info_summary(info: dict, target_time_zone: str | None = None) -> dict:
    events = info.get("events")
    summary = {}
    if info.get("status_id") is not None:
        summary["is_online"] = info.get("status_id") == 1
    if not isinstance(events, list):
        return summary
    summary["events_count"] = len(events)
    if events and isinstance(events[0], dict):
        latest = events[0]
        for field in ("event", "event_type_id", "date", "time"):
            if latest.get(field) not in (None, ""):
                summary[f"latest_event_{field}"] = latest[field]
        local_event = _format_local_datetime(
            latest.get("date"),
            latest.get("time"),
            target_time_zone,
        )
        if local_event:
            local_date, local_time, iso_value = local_event
            summary["latest_event_raw_date"] = latest.get("date")
            summary["latest_event_raw_time"] = latest.get("time")
            summary["latest_event_date"] = local_date
            summary["latest_event_time"] = local_time
            summary["latest_event_datetime"] = iso_value
    for event in events:
        if isinstance(event, dict) and _is_toilet_event(event):
            summary.update(_toilet_event_summary(event, target_time_zone))
            break
    return summary


class NottyCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, api: NottyApi, entry: ConfigEntry | None = None):
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            always_update=False,
            config_entry=entry,
        )
        self.api = api

    async def _async_update_data(self):
        try:
            devices = await self.api.devices()
            out: dict[str, dict[str, Any]] = {}
            for device in devices:
                did = _device_id(device)
                if not did:
                    continue

                device_type = _device_type(device)
                if device_type != "litter_box":
                    _LOGGER.debug("Skipping non-litter-box NOTTY device payload: %s", device)
                    continue

                if device.get("_notty_source") == "pet":
                    pet_id = str(device.get("pet_id") or "").removeprefix("pet_")
                    related = await self.api.pet_related_info(pet_id) if pet_id else {}
                    info = {
                        **device,
                        **_pet_related_summary(related),
                        "litter_user_device_id": device.get("_notty_litter_user_device_id"),
                        "_notty_related": related,
                    }
                    _merge_scalar_fields(info, device)
                else:
                    info = await self.api.device_info(did, device_type)
                    if device_type == "litter_box":
                        target_time_zone = (
                            info.get("time_zone_iana")
                            or device.get("time_zone_iana")
                            or self.hass.config.time_zone
                        )
                        related = await self.api.litter_related_info(did)
                        info = {
                            **info,
                            **_litter_info_summary(info, target_time_zone),
                            **_litter_related_summary(related, target_time_zone),
                            "_notty_related": related,
                        }
                        unread_count = await self.api.unread_message_count()
                        if unread_count is not None:
                            info["unread_message_count"] = unread_count
                        _merge_related_pet_blocks(out, device, did, related)
                if not info:
                    _LOGGER.debug(
                        "Skipping NOTTY litter box without bound info payload: %s", device
                    )
                    continue
                _merge_block(out, did, device, info, device_type)
            if self.config_entry is not None:
                data = dict(self.config_entry.data)
                for key, value in (
                    (CONF_ACCESS_TOKEN, self.api.token),
                    (CONF_REFRESH_TOKEN, self.api.refresh_token),
                    (CONF_USER_ID, self.api.user_id),
                ):
                    if value:
                        data[key] = value
                if data != self.config_entry.data:
                    self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return out
        except NottyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NottyApiError as err:
            raise UpdateFailed(str(err)) from err
