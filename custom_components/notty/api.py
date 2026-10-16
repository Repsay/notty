from __future__ import annotations

from datetime import UTC, date, datetime, time
import json
import logging
import re
from typing import TypedDict, Unpack, cast
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

HTTP_ERROR_STATUS = 400
ACTION_ONE_KEY = "one_key"
ACTION_SET_AUTO_DELAY = "set_auto_delay"
PLAN_ADD = "add_plan"
PLAN_EDIT = "edit_plan"
PLAN_OPEN = "open_plan"
PLAN_DELETE = "delete_plan"
PLAN_FIELDS = {
    PLAN_ADD: {"time"},
    PLAN_EDIT: {"plan_id", "time"},
    PLAN_OPEN: {"plan_id", "open"},
    PLAN_DELETE: {"plan_id"},
}
PLAN_ACTIONS = set(PLAN_FIELDS)
PLAN_TIME_RE = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
MAX_LITTER_PLANS = 10


ACTION_SET_MODE = "set_mode"
DEVICE_TYPE_LITTER_BOX = "litter_box"
ONE_KEY_ACTIONS = {"clean": 1, "empty": 2, "level": 3}
LITTER_MODES = {1: "Auto", 2: "Scheduled", 3: "Soft stool"}
MAX_DELAY_MINUTES = 15

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]

BASE_URL = "https://api.nottycat.com"
APP_USER_AGENT = "4.1.0;android;6.0.1;default;A001"
LOGIN_CODE_TYPE_ID = 1
LOGIN_DEVICE_ID = "1"
APP_VERSION_NUMBER = "1.1.30+76"
DEFAULT_CLIENT_ID = "0"
DEVICE_INFO_PATHS = {"litter_box": "/device/litter_box/get_info/"}
LITTER_READ_ENDPOINTS = {
    "plans": "/device/litter_box/plans/",
    "guide": "/device/litter_box/get_guide/",
    "pet_data_list": "/device/litter_box/pet_data_list/",
    "messages": "/device/get_message/",
    "daily_event_counts": "/device/get_daily_event_counts/",
    "associated_pets": "/device/get_associated_pets/",
    "associated_users": "/device/get_associated_users/",
    "upgrade": "/device/check_upgrade/",
}
PET_READ_ENDPOINTS = {
    "info": "/pet/info/{pet_id}",
    "wc_statistics": "/pet/pet_wc_data_statistics?pet_id={pet_id}",
    "memos": "/pet/memos/{pet_id}",
    "associated_users": "/pet/get_associated_users/{pet_id}",
}
LITTER_PET_READ_ENDPOINTS = {
    "pet_data_statistics": "/device/litter_box/pet_data_statistics/{device_id}?pet_id={pet_id}",
    "pet_data_detail": "/device/litter_box/pet_data_detail/{device_id}?pet_id={pet_id}",
}
LITTER_ACTION_ENDPOINTS = {
    "one_key": "/device/litter_box/one_key",
    "set_mode": "/device/litter_box/set_mode",
    "set_key": "/device/litter_box/set_key",
    "reset_litter_reminder": "/device/litter_box/set_litter_remind",
    "reset_garbage_bag_reminder": "/device/litter_box/set_garbage_bag_remind",
    "set_litter_reminder_days": "/device/litter_box/set_litter_remind",
    "set_garbage_bag_reminder_days": "/device/litter_box/set_garbage_bag_remind",
    "set_litter_remind": "/device/litter_box/set_litter_remind",
    "set_garbage_bag_remind": "/device/litter_box/set_garbage_bag_remind",
    "set_auto_delay": "/device/litter_box/set_auto_delay",
    "set_dnd": "/device/litter_box/set_dnd",
    "set_language": "/device/litter_box/set_language",
    "add_plan": "/device/litter_box/add_plan",
    "edit_plan": "/device/litter_box/edit_plan",
    "delete_plan": "/device/litter_box/delete_plan",
    "open_plan": "/device/litter_box/open_plan",
    "reset_device_weight": "/device/litter_box/reset_device_weight",
    "horizontal_calibration": "/device/litter_box/horizontal_calibration",
    "confirm_upgrade": "/device/confirm_upgrade",
    "set_alias": "/device/set_alias",
    "clear_statistics": "/device/clear_statistics/",
}
SAFE_LITTER_ACTIONS = (
    "one_key",
    "set_key",
    "reset_litter_reminder",
    "reset_garbage_bag_reminder",
    "set_litter_reminder_days",
    "set_garbage_bag_reminder_days",
    "set_dnd",
    "set_language",
    "reset_device_weight",
    "horizontal_calibration",
)
REMINDER_CYCLE_FIELDS = {
    "set_litter_remind": "default_remaining_days",
    "reset_litter_reminder": "default_remaining_days",
    "set_litter_reminder_days": "default_remaining_days",
    "set_garbage_bag_remind": "garbage_bag_cycle_time",
    "reset_garbage_bag_reminder": "garbage_bag_cycle_time",
    "set_garbage_bag_reminder_days": "garbage_bag_cycle_time",
}
REMINDER_DAY_RANGES = {"default_remaining_days": range(5, 31), "garbage_bag_cycle_time": range(2, 16)}
REMINDER_ENABLE = 1
REMINDER_DISABLE = 2
REMINDER_UPDATE = 3
REMINDER_LITTER_INTERVAL_ACTION = "set_litter_reminder_days"
REMINDER_TOGGLE_ACTIONS = {"set_litter_remind", "set_garbage_bag_remind"}

LIST_KEYS = ("list", "devices", "rows", "items", "data")
LITTER_BIND_KEYS = ("bind_litter_box", "litter_box", "litter_box_id", "litter_box_user_device_id", "lb_user_device_id")
_LOGGER = logging.getLogger(__name__)


def matches_value(value: object, choices: tuple[object, ...]) -> bool:
    """Compare JSON values without requiring hashability.

    Returns:
        Whether the value equals one of the explicit choices.
    """
    return any(value == choice for choice in choices)


class NottyApiError(Exception):
    """Base NOTTY API error."""


class NottyAuthError(NottyApiError):
    """Authentication failed."""


def plan_id(value: JsonValue) -> str:
    """Validate a plan identifier without coercing booleans or missing values.

    Returns:
        An identifier suitable for exact matching against a device's plan list.

    Raises:
        NottyApiError: If the identifier is empty or malformed.
    """
    if type(value) is int and value > 0:
        return str(value)
    msg = "A valid nonempty plan_id is required"
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise NottyApiError(msg)
    if value.lstrip("+-").isdecimal() and int(value) <= 0:
        raise NottyApiError(msg)
    return value


def plan_enabled(value: JsonValue) -> bool | None:
    """Decode only recognized read-state representations.

    Returns:
        True, False, or None for an unknown state.
    """
    if isinstance(value, (bool, int, str)):
        if value in {True, "1", "true"}:
            return True
        if value in {False, "0", "false"}:
            return False
    return None


def plan_rows(value: JsonValue) -> list[JsonObject]:
    """Require a complete plan list before allowing any mutation.

    Returns:
        The rows with unique, usable plan identifiers.

    Raises:
        NottyApiError: If the response is not a list of uniquely identified objects.
    """
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        msg = "NOTTY returned an invalid schedule list"
        raise NottyApiError(msg)
    rows = cast("list[JsonObject]", value)
    identifiers = [plan_id(row.get("plan_id")) for row in rows]
    if len(set(identifiers)) != len(identifiers):
        msg = "NOTTY returned ambiguous schedule IDs"
        raise NottyApiError(msg)
    return rows


def _plan_target(
    action: str, data: JsonObject, rows: list[JsonObject], device_id: str
) -> tuple[JsonObject, JsonObject]:
    if action == PLAN_ADD:
        if len(rows) >= MAX_LITTER_PLANS:
            msg = "NOTTY supports at most ten cleaning plans"
            raise NottyApiError(msg)
        return {"user_device_id": device_id}, {}
    target = plan_id(data.get("plan_id"))
    matches = [row for row in rows if plan_id(row.get("plan_id")) == target]
    if len(matches) != 1:
        msg = "The selected plan_id does not belong to this litter box"
        raise NottyApiError(msg)
    current = matches[0]
    return {"plan_id": current["plan_id"]}, current


def _plan_time_fields(data: JsonObject, current: JsonObject) -> JsonObject:
    clock = data.get("time")
    if not isinstance(clock, str) or not PLAN_TIME_RE.fullmatch(clock):
        msg = "Schedule time must be a NOTTY clock value in HH:MM format"
        raise NottyApiError(msg)
    for field in ("quantity", "plan_type_id"):
        value = current.get(field, 1)
        if type(value) is not int or value != 1:
            msg = "Cannot edit an unsupported schedule quantity or recurrence type"
            raise NottyApiError(msg)
    return {"time": clock, "quantity": 1}


def plan_payload(action: str, data: JsonObject, rows: list[JsonObject], device_id: str) -> JsonObject:
    """Build only fields established by the app's litter-box schedule callers.

    Returns:
        A narrowly targeted request, preserving the reported plan ID type.

    Raises:
        NottyApiError: If targeting, time, state or plan support is invalid.
    """
    if action not in PLAN_ACTIONS:
        msg = "Unsupported schedule action"
        raise NottyApiError(msg)
    if set(data) != PLAN_FIELDS[action]:
        msg = f"Schedule {action} requires exactly: {', '.join(sorted(PLAN_FIELDS[action]))}"
        raise NottyApiError(msg)
    payload, current = _plan_target(action, data, rows, device_id)
    if action in {PLAN_ADD, PLAN_EDIT}:
        payload.update(_plan_time_fields(data, current))
    if action == PLAN_OPEN:
        enabled = data.get("open")
        if type(enabled) is not bool:
            msg = "Schedule open must be a Boolean"
            raise NottyApiError(msg)
        payload["open"] = enabled
    return payload


def one_key_value(action: JsonValue) -> int:
    """Resolve only the operations traced through app callers and serialization.

    Returns:
        The integer sent as one_key by the app.

    Raises:
        NottyApiError: If an operation has no established litter-box contract.
    """
    if isinstance(action, str) and action in ONE_KEY_ACTIONS:
        return ONE_KEY_ACTIONS[action]
    if type(action) is int and action in ONE_KEY_ACTIONS.values():
        return action
    msg = "Unsupported litter-box one_key value; use clean=1, empty=2, or level=3"
    raise NottyApiError(msg)


def timezone_catalog(value: JsonValue) -> list[JsonObject]:
    """Validate the live catalog without inventing IDs or DST offsets.

    Returns:
        Public catalog fields with exact server-provided strings.

    Raises:
        NottyApiError: If any required field or identifier is invalid.
    """
    if not isinstance(value, list) or not value:
        msg = "NOTTY timezone catalog must be a nonempty array"
        raise NottyApiError(msg)
    rows: list[JsonObject] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            msg = "Invalid NOTTY timezone catalog record"
            raise NottyApiError(msg)
        row: JsonObject = {}
        for key in ("id", "display_name", "offset"):
            field = item.get(key)
            if not isinstance(field, str) or not field.strip() or not field.isprintable():
                msg = "Invalid NOTTY timezone catalog string"
                raise NottyApiError(msg)
            row[key] = field
        identifier = str(row["id"])
        if identifier in seen:
            msg = "Duplicate NOTTY timezone catalog ID"
            raise NottyApiError(msg)
        seen.add(identifier)
        rows.append(row)
    return rows


def timezone_payload(device_id: str, catalog_id: str, rows: list[JsonObject]) -> JsonObject:
    """Use the selected Windows catalog ID in the APK's misnamed IANA field.

    Returns:
        Only the two fields serialized by the app.

    Raises:
        NottyApiError: If the physical ID or catalog membership is invalid.
    """
    if not device_id.isascii() or not device_id.isdecimal() or int(device_id) <= 0:
        msg = "Timezone changes require a positive numeric physical device ID"
        raise NottyApiError(msg)
    if not any(row["id"] == catalog_id for row in rows):
        msg = "Choose an exact ID from the current NOTTY timezone catalog"
        raise NottyApiError(msg)
    return {"user_device_id": int(device_id), "time_zone_iana": catalog_id}


def reminder_payload(action: str, data: JsonObject) -> JsonObject:
    """Build a validated reminder request using owner-observed live operation codes.

    Litter interval changes (3) were verified on an already enabled reminder;
    reset and trash-bag interval changes remain blocked pending live testing.

    Returns:
        Only the validated operation and configured cycle, without read fields.

    Raises:
        NottyApiError: If an action or configured interval is unverified.
    """
    if action == REMINDER_LITTER_INTERVAL_ACTION:
        operation = data.get("action", REMINDER_UPDATE)
        if type(operation) is not int or operation != REMINDER_UPDATE:
            msg = "Litter interval action must use action=3"
            raise NottyApiError(msg)
    elif action in REMINDER_TOGGLE_ACTIONS:
        operation = data.get("action")
        if type(operation) is not int or operation not in {REMINDER_ENABLE, REMINDER_DISABLE}:
            msg = "Reminder action must be an integer: enable=1, disable=2"
            raise NottyApiError(msg)
    else:
        msg = "Reminder reset and trash bag interval changes are disabled pending live endpoint verification"
        raise NottyApiError(msg)
    cycle = data.get("cycle_time")
    if isinstance(cycle, str) and cycle.isascii() and cycle.isdecimal():
        cycle = int(cycle)
    allowed = REMINDER_DAY_RANGES[REMINDER_CYCLE_FIELDS[action]]
    if type(cycle) is not int or cycle not in allowed:
        msg = f"Reminder cycle_time must be an integer from {allowed.start} to {allowed.stop - 1} days"
        raise NottyApiError(msg)
    return {"action": operation, "cycle_time": cycle}


DND_READ_TIME_ZONE = "Asia/Shanghai"
DND_TIME_FIELDS = ("dnd_begin_time", "dnd_end_time")


def _dnd_clock(value: JsonValue) -> time:
    """Validate a time-of-day without accepting offsets or seconds.

    Returns:
        A timezone-free clock value.

    Raises:
        NottyApiError: If the clock value is unavailable or invalid.
    """
    try:
        parsed = time.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        msg = "Cannot preserve current Do Not Disturb interval"
        raise NottyApiError(msg)
    return parsed


def _dnd_shift_time(
    value: JsonValue, source_time_zone: str, target_time_zone: str, *, at: datetime | None = None
) -> time:
    """Translate recurring clock values using offsets at a single instant.

    NOTTY returns recurring wall times with no calendar date, so a future
    DST-boundary offset cannot be inferred from the response itself.

    Returns:
        A clock time in the target timezone.

    Raises:
        NottyApiError: If the time or timezone is invalid.
    """
    parsed = _dnd_clock(value)
    try:
        source_zone = ZoneInfo(source_time_zone)
        target_zone = ZoneInfo(target_time_zone)
    except (KeyError, ZoneInfoNotFoundError, ValueError) as exc:
        msg = "Cannot convert Do Not Disturb times without valid IANA timezones"
        raise NottyApiError(msg) from exc
    moment = at or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        msg = "Cannot convert Do Not Disturb times without an aware reference instant"
        raise NottyApiError(msg)
    source_offset = moment.astimezone(source_zone).utcoffset()
    target_offset = moment.astimezone(target_zone).utcoffset()
    if source_offset is None or target_offset is None:
        msg = "Cannot determine Do Not Disturb timezone offset"
        raise NottyApiError(msg)
    return (datetime.combine(date(2000, 1, 1), parsed) + (target_offset - source_offset)).time()


def dnd_time_zone(current: JsonObject, *, fallback: str | None = None) -> str:
    """Resolve the device's configured IANA zone, falling back only if absent.

    Returns:
        A validated IANA timezone name.

    Raises:
        NottyApiError: If no usable timezone is available.
    """
    configured = current.get("time_zone_iana")
    if not configured:
        configured = fallback
    if not isinstance(configured, str) or not configured:
        msg = "Cannot change Do Not Disturb without a NOTTY or fallback IANA timezone"
        raise NottyApiError(msg)
    try:
        ZoneInfo(configured)
    except (KeyError, ZoneInfoNotFoundError, ValueError) as exc:
        msg = "Invalid reported Do Not Disturb device timezone"
        raise NottyApiError(msg) from exc
    return configured


def dnd_local_time(value: JsonValue, time_zone: str, *, at: datetime | None = None) -> time:
    """Convert API readback (apparent Shanghai clock) directly into HA time.

    Returns:
        The converted local clock value.
    """
    return _dnd_shift_time(value, DND_READ_TIME_ZONE, time_zone, at=at)


def dnd_payload(
    current: JsonObject,
    *,
    time_zone: str | None = None,
    input_time_zone: str | None = None,
    at: datetime | None = None,
    **changes: JsonValue,
) -> JsonObject:
    """Send device-local clock times; never echo the shifted API readback.

    Prefer NOTTY's time_zone_iana to any caller-provided fallback. HA edits
    are in HA's timezone and must be converted again to device-local time.

    Returns:
        A validated DND request containing device-local clock values.

    Raises:
        NottyApiError: If any preserved setting or zone is unknown or invalid.
    """
    device_zone = dnd_time_zone(current, fallback=time_zone)
    state = {**current, **changes}
    enabled = state.get("switch_dnd")
    if not isinstance(enabled, (bool, int, str)) or enabled not in {0, 1, "0", "1"}:
        msg = "Cannot preserve unknown Do Not Disturb switch state"
        raise NottyApiError(msg)
    led = state.get("led")
    if not ((isinstance(led, int) and led >= 0) or (isinstance(led, str) and led.isascii() and led.isdecimal())):
        msg = "Cannot preserve unknown LED setting for Do Not Disturb"
        raise NottyApiError(msg)
    payload: JsonObject = {"switch": int(enabled), "led": led}
    for key in DND_TIME_FIELDS:
        if key in changes:
            # Explicit user edits are in HA timezone, unless a standalone
            # caller passes device-local values without an input timezone.
            source_zone = input_time_zone or device_zone
            parsed = _dnd_shift_time(changes[key], source_zone, device_zone, at=at)
        else:
            parsed = dnd_local_time(current.get(key), device_zone, at=at)
        payload[key] = parsed.strftime("%H:%M")
    if payload["switch"] and payload["dnd_begin_time"] == payload["dnd_end_time"]:
        msg = "Cannot enable Do Not Disturb with identical start/end times"
        raise NottyApiError(msg)
    return payload


class ConnectionOptions(TypedDict, total=False):
    """Optional NOTTY account and session parameters."""

    email: str | None
    verification_code: str | None
    token: str | None
    refresh_token: str | None
    user_id: str | int | None
    client_id: str
    region_code: str


class NottyTransport:
    """HTTP transport that propagates expired sessions without replaying requests."""

    def __init__(self, session: aiohttp.ClientSession, **options: Unpack[ConnectionOptions]) -> None:
        self._session = session
        email = options.get("email")
        verification_code = options.get("verification_code")
        user_id = options.get("user_id")
        self.email = email.strip() if email else email
        self.verification_code = verification_code.strip() if verification_code else verification_code
        self.token = options.get("token")
        self.refresh_token = options.get("refresh_token")
        self.user_id = str(user_id) if not matches_value(user_id, (None, "")) else None
        self.client_id = options.get("client_id", DEFAULT_CLIENT_ID)
        self.region_code = options.get("region_code", "NL")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en",
            "Content-Type": "application/json",
            "User-Agent": APP_USER_AGENT,
            "User-Aagent": APP_USER_AGENT,
            "HZUID": self.user_id or "2",
            "XJiang-Language": "en",
        }
        if self.region_code:
            headers["xjiang_region_id"] = self.region_code
        if self.token:
            raw_token = self.token.removeprefix("Bearer ").removeprefix("bearer ")
            headers["Authorization"] = raw_token
            headers["access_token"] = raw_token
        return headers

    @staticmethod
    def unwrap(payload: JsonValue) -> JsonValue:
        """Unwrap.

        Returns:
            JsonValue: The resulting unwrap.

        Raises:
            NottyApiError: When the requested operation cannot be completed.
            NottyAuthError: When the cloud session is rejected.
            NottyAuthError: When the requested operation cannot be completed.
        """
        if isinstance(payload, dict):
            code = payload.get("code", payload.get("error_code"))
            if not matches_value(code, (None, 0, 200, "0", "200")):
                message = payload.get("message") or payload.get("msg") or str(payload)
                if str(code) in {"401", "403", "1001", "1002"}:
                    raise NottyAuthError(message)
                raise NottyApiError(message)
            for key in ("data", "result"):
                if key in payload:
                    return payload[key]
        return payload

    async def raw_request(
        self,
        method: str,
        url: str,
        *,
        data: JsonObject | None = None,
        form: JsonObject | None = None,
        authenticated: bool = True,
    ) -> JsonValue:
        """Raw request.

        Returns:
            JsonValue: The resulting raw request.

        Raises:
            NottyApiError: When the requested operation cannot be completed.
            NottyAuthError: When the cloud session is rejected.
            NottyAuthError: When the requested operation cannot be completed.
        """
        headers = (
            self._headers()
            if authenticated
            else {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en",
                "Content-Type": "application/json" if form is None else "application/x-www-form-urlencoded",
                "User-Agent": APP_USER_AGENT,
                "User-Aagent": APP_USER_AGENT,
                "HZUID": "2",
                "XJiang-Language": "en",
            }
        )
        if not authenticated and self.region_code:
            headers["xjiang_region_id"] = self.region_code
        try:
            async with self._session.request(
                method, url, json=data, data=form, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                text = await response.text()
                response_status = response.status
        except TimeoutError as err:
            msg = "Timeout contacting NOTTY"
            raise NottyApiError(msg) from err
        except aiohttp.ClientError as err:
            raise NottyApiError(str(err)) from err
        if response_status in {401, 403}:
            message = f"HTTP {response_status}"
            raise NottyAuthError(message)
        if response_status >= HTTP_ERROR_STATUS:
            message = f"HTTP {response_status}"
            raise NottyApiError(message)
        try:
            payload = cast("JsonValue", json.loads(text))
        except json.JSONDecodeError:
            return {"raw": text}
        return self.unwrap(payload)

    async def request(self, method: str, path: str, *, data: JsonObject | None = None) -> JsonValue:
        """Send one request and let Home Assistant handle expired sessions.

        Returns:
            The decoded NOTTY response.
        """
        return await self.raw_request(method, f"{BASE_URL}{path}", data=data)

    async def verify_token(self) -> JsonValue:
        """Verify token.

        Returns:
            JsonValue: The resulting verify token.
        """
        return await self.request("GET", "/account/verify_token")

    async def endpoint_action(self, device_id: str, path: str) -> JsonValue:
        """Endpoint action.

        Returns:
            JsonValue: The resulting endpoint action.
        """
        return await self.request("POST", path, data=self._device_payload(device_id))

    @staticmethod
    def _device_payload(device_id: str) -> JsonObject:
        return {"user_device_id": device_id, "device_id": device_id}


class NottyApi(NottyTransport):
    """NOTTY account, litter-box and pet endpoints."""

    async def time_zones(self) -> list[JsonObject]:
        """Read the supported catalog on explicit request.

        Returns:
            Validated public timezone records.
        """
        return timezone_catalog(await self.request("GET", "/entity/get_time_zones"))

    async def change_time_zone(self, device_id: str, catalog_id: str) -> JsonValue:
        """Validate fresh catalog membership before one explicit timezone write.

        Returns:
            The server acknowledgement, not proof of schedule preservation.
        """
        rows = await self.time_zones()
        return await self.request(
            "POST", "/device/change_time_zone", data=timezone_payload(device_id, catalog_id, rows)
        )

    @staticmethod
    def _find_first(result: JsonValue, keys: tuple[str, ...]) -> JsonValue:
        if isinstance(result, dict):
            for key in keys:
                if key in result and not matches_value(result[key], (None, "")):
                    return result[key]
            for value in result.values():
                found = NottyApi._find_first(value, keys)
                if not matches_value(found, (None, "")):
                    return found
        elif isinstance(result, list):
            for item in result:
                found = NottyApi._find_first(item, keys)
                if not matches_value(found, (None, "")):
                    return found
        return None

    @staticmethod
    def _as_list(result: JsonValue) -> list[JsonObject]:
        if isinstance(result, dict):
            for key in LIST_KEYS:
                value = result.get(key)
                if isinstance(value, list):
                    result = value
                    break
            else:
                result = []
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    @staticmethod
    def _bound_litter_id(pet: JsonObject) -> str | None:
        for key in LITTER_BIND_KEYS:
            value = pet.get(key)
            if isinstance(value, bool) or matches_value(value, (None, "", 0, "0")):
                continue
            if isinstance(value, dict):
                found = NottyApi._find_first(value, ("user_device_id", "device_id", "id", "did"))
                if not matches_value(found, (None, "", 0, "0")):
                    return str(found)
                continue
            if isinstance(value, list):
                found = NottyApi._find_first(value, ("user_device_id", "device_id", "id", "did"))
                if not matches_value(found, (None, "", 0, "0")):
                    return str(found)
                continue
            return str(value)
        return None

    @staticmethod
    def pet_litter_device_id(pet: JsonObject) -> str | None:
        """Pet litter device id.

        Returns:
            str | None: The resulting pet litter device id.
        """
        for key in ("_notty_litter_user_device_id", "litter_user_device_id"):
            value = pet.get(key)
            if not matches_value(value, (None, "", 0, "0")):
                return str(value)

        bound_id = NottyApi._bound_litter_id(pet)
        if bound_id:
            return bound_id

        pet_devices = pet.get("pet_devices")
        if isinstance(pet_devices, list):
            for bound_device in pet_devices:
                if not isinstance(bound_device, dict) or bound_device.get("is_bind") is False:
                    continue
                for key in ("user_device_id", "device_id", "id", "did"):
                    found = bound_device.get(key)
                    if not matches_value(found, (None, "", 0, "0")):
                        return str(found)
        return None

    @staticmethod
    def _pet_has_litter_data(pet: JsonObject) -> bool:
        if pet.get("bind_litter_box") or pet.get("has_litter_box_data"):
            return True
        for key in ("today_wc_count", "today_wc_duration", "yesterday_wc_count", "yesterday_wc_duration", "wc_status"):
            if not matches_value(pet.get(key), (None, "", 0, "0")):
                return True
        return False

    @staticmethod
    def pet_litter_device(pet: JsonObject) -> JsonObject | None:
        """Pet litter device.

        Returns:
            JsonObject | None: The resulting pet litter device.
        """
        device_id = NottyApi.pet_litter_device_id(pet)
        has_litter_data = NottyApi._pet_has_litter_data(pet)
        pet_id = pet.get("pet_id") or pet.get("id")
        if not device_id and (not has_litter_data or matches_value(pet_id, (None, ""))):
            return None
        pet_name = pet.get("alias") or pet.get("name") or pet.get("pet_name")
        return {
            **pet,
            "_notty_source": "pet",
            "_notty_has_device_id": False,
            "_notty_litter_user_device_id": str(device_id) if device_id else None,
            "device_type": "litter_box",
            "product_name": "Cat Automatic Litter Box",
            "pet_id": pet_id,
            "alias": pet_name or pet.get("alias"),
            "model": "Litter Box Pet",
            "id": f"pet_{pet_id}",
        }

    @staticmethod
    def _extract_login(result: JsonValue) -> tuple[str | None, str | None, str | None]:
        if not isinstance(result, dict):
            return None, None, None
        token = NottyApi._find_first(result, ("access_token", "accessToken", "token"))
        refresh = NottyApi._find_first(result, ("refresh_token", "refreshToken"))
        user_id = result.get("user_id") or result.get("userId") or result.get("uid")
        if matches_value(user_id, (None, "")):
            user = result.get("user") or result.get("userInfo") or result.get("account")
            user_id = NottyApi._find_first(user, ("user_id", "userId", "uid", "id"))
        return (
            str(token) if token else None,
            str(refresh) if refresh else None,
            str(user_id) if not matches_value(user_id, (None, "")) else None,
        )

    async def request_email_code(self) -> JsonValue:
        """Request email code.

        Returns:
            JsonValue: The resulting request email code.

        Raises:
            NottyAuthError: When the requested operation cannot be completed.
        """
        if not self.email:
            msg = "Email address is required"
            raise NottyAuthError(msg)
        return await self.raw_request(
            "POST",
            f"{BASE_URL}/account/get_email_code",
            data={"email": self.email, "code_type_id": LOGIN_CODE_TYPE_ID, "client_id": self.client_id},
            authenticated=False,
        )

    async def _login_with_email_code(self) -> bool:
        if not self.email or not self.verification_code:
            return False
        result = await self.raw_request(
            "POST",
            f"{BASE_URL}/account/login_by_email",
            data={
                "email": self.email,
                "code": self.verification_code,
                "device_id": LOGIN_DEVICE_ID,
                "version_number": APP_VERSION_NUMBER,
            },
            authenticated=False,
        )
        token, refresh, user_id = self._extract_login(result)
        if token:
            self.token = token
            self.refresh_token = refresh
            self.user_id = user_id
            return True
        _LOGGER.debug("NOTTY email-code login response contained no NOTTY access token")
        return False

    async def login(self) -> str:
        """Authenticate with a single email-code request, then validate discovery.

        Returns:
            The NOTTY access token.

        Raises:
            NottyAuthError: When an email or code is missing, or the response has no access token.
        """
        if not self.email:
            message = "Email address is required"
            raise NottyAuthError(message)
        if not self.verification_code:
            message = "A fresh email verification code is required; password login is unsupported"
            raise NottyAuthError(message)
        try:
            accepted = await self._login_with_email_code()
        finally:
            # Codes must never be reused by a request retry or kept in a session.
            self.verification_code = None
        if not accepted:
            message = "Email-code login response contained no NOTTY access token"
            raise NottyAuthError(message)
        await self.devices()
        return self.token or ""

    async def pets(self) -> list[JsonObject]:
        """Pets.

        Returns:
            list[JsonObject]: The resulting pets.
        """
        return self._as_list(await self.request("GET", "/pet/list"))

    @staticmethod
    def _litter_pet_ids(pets: list[JsonObject]) -> list[str]:
        pet_ids: list[str] = []
        for pet in pets:
            if not NottyApi._pet_has_litter_data(pet):
                continue
            pet_id = pet.get("pet_id") or pet.get("id")
            if not matches_value(pet_id, (None, "")):
                pet_ids.append(str(pet_id))
        return pet_ids

    @staticmethod
    def _merge_user_devices(
        discovered: dict[str, JsonObject], rows: list[JsonObject], *, pet_id: str | None = None
    ) -> None:
        for device in rows:
            device_id = str(device.get("user_device_id") or device.get("id") or "")
            if not device_id:
                continue
            merged = {
                **discovered.get(device_id, {}),
                **device,
                "_notty_source": "device",
                "_notty_has_device_id": True,
            }
            if pet_id is not None:
                existing_ids = discovered.get(device_id, {}).get("_notty_pet_ids")
                pet_ids = {str(item) for item in existing_ids} if isinstance(existing_ids, list) else set()
                pet_ids.add(pet_id)
                merged["_notty_pet_ids"] = cast("list[JsonValue]", sorted(pet_ids))
            discovered[device_id] = merged

    async def _discovery_pet_ids(self, pets: list[JsonObject] | None) -> list[str]:
        return self._litter_pet_ids(pets if pets is not None else await self.pets())

    @staticmethod
    def _discovery_results(discovered: dict[str, JsonObject], errors: list[str]) -> list[JsonObject]:
        if discovered:
            return list(discovered.values())
        if errors:
            raise NottyApiError("; ".join(errors))
        return []

    async def user_devices(self, pets: list[JsonObject] | None = None) -> list[JsonObject]:
        """User devices.

        Returns:
            list[JsonObject]: The resulting user devices.

        Raises:
            NottyAuthError: When the cloud session is rejected.
        """
        errors: list[str] = []
        discovered: dict[str, JsonObject] = {}

        for pet_id in await self._discovery_pet_ids(pets):
            try:
                rows = self._as_list(await self.request("GET", f"/device/get_user_devices/{pet_id}"))
            except NottyAuthError:
                raise
            except NottyApiError as err:
                errors.append(f"GET /device/get_user_devices/{pet_id}: {err}")
            else:
                self._merge_user_devices(discovered, rows, pet_id=pet_id)

        for path in ("/device/get_user_devices/2", "/device/get_user_devices/"):
            try:
                rows = self._as_list(await self.request("GET", path))
            except NottyAuthError:
                raise
            except NottyApiError as err:
                errors.append(f"GET {path}: {err}")
            else:
                self._merge_user_devices(discovered, rows)

        return self._discovery_results(discovered, errors)

    def _merge_discovered_pets(self, discovered: dict[str, JsonObject], pets: list[JsonObject]) -> None:
        pet_parents: dict[str, set[str]] = {}
        for physical in discovered.values():
            parent_id = physical.get("user_device_id")
            if matches_value(parent_id, (None, "")):
                continue
            associated_ids = physical.get("_notty_pet_ids")
            if not isinstance(associated_ids, list):
                continue
            for pet_id in associated_ids:
                pet_parents.setdefault(str(pet_id), set()).add(str(parent_id))

        for pet in pets:
            pet_device = self.pet_litter_device(pet)
            if pet_device:
                device = pet_device
                # Boolean bind_litter_box indicates a binding, but provides no device ID.
                parents = pet_parents.get(str(device["pet_id"]), set())
                if not device.get("_notty_litter_user_device_id") and len(parents) == 1:
                    device["_notty_litter_user_device_id"] = next(iter(parents))
                device_id = str(device.get("id"))
                discovered[device_id] = {**discovered.get(device_id, {}), **device}

    async def devices(self) -> list[JsonObject]:
        """Devices.

        Returns:
            list[JsonObject]: The resulting devices.

        Raises:
            NottyApiError: When the requested operation cannot be completed.
            NottyAuthError: When the cloud session is rejected.
        """
        errors: list[str] = []
        discovered: dict[str, JsonObject] = {}
        account_endpoint_ok = False

        try:
            pets = await self.pets()
        except NottyAuthError:
            raise
        except NottyApiError as err:
            pets = []
            errors.append(f"/pet/list: {err}")

        try:
            for device in await self.user_devices(pets):
                device_id = str(device.get("user_device_id") or device.get("id") or "")
                if device_id:
                    discovered[device_id] = device
            account_endpoint_ok = True
        except NottyAuthError:
            raise
        except NottyApiError as err:
            errors.append(f"/device/get_user_devices/<pet_id>: {err}")

        self._merge_discovered_pets(discovered, pets)
        if pets:
            account_endpoint_ok = True

        if discovered or account_endpoint_ok:
            return list(discovered.values())
        raise NottyApiError("; ".join(errors) or "No supported device list endpoint returned devices")

    async def device_info(self, device_id: str, device_type: str) -> JsonObject:
        """Device info.

        Returns:
            JsonObject: The resulting device info.

        Raises:
            NottyAuthError: When the cloud session is rejected.
        """
        base_path = DEVICE_INFO_PATHS.get(device_type)
        if not base_path:
            return {}

        for method, path, data in (
            ("GET", f"{base_path}{device_id}", None),
            ("GET", base_path, self._device_payload(device_id)),
            ("POST", base_path, self._device_payload(device_id)),
        ):
            try:
                result = await self.request(method, path, data=data)
                return result if isinstance(result, dict) else {"data": result}
            except NottyAuthError:
                raise
            except NottyApiError:
                _LOGGER.debug("Optional NOTTY endpoint unavailable: %s", path)
                continue
        return {}

    async def litter_info(self, device_id: str) -> JsonObject:
        """Litter info.

        Returns:
            JsonObject: The resulting litter info.
        """
        return await self.device_info(device_id, "litter_box")

    @staticmethod
    def _related_value(key: str, result: JsonValue) -> JsonObject:
        values: JsonObject = {key: result}
        items = result if isinstance(result, list) else NottyApi._as_list(result)
        if items or isinstance(result, list):
            values[f"{key}_count"] = len(items)
        return values

    async def _read_litter_related(self, device_id: str, key: str, base_path: str) -> JsonObject:
        for method, path, data in (
            ("GET", f"{base_path}{device_id}", None),
            ("POST", base_path, self._device_payload(device_id)),
        ):
            try:
                result = await self.request(method, path, data=data)
            except NottyAuthError:
                raise
            except NottyApiError:
                _LOGGER.debug("Optional NOTTY endpoint unavailable: %s", path)
            else:
                return self._related_value(key, result)
        return {}

    @staticmethod
    def _related_pet_rows(related: JsonObject) -> dict[str, JsonObject]:
        pet_rows: dict[str, JsonObject] = {}
        for source_key in ("associated_pets", "pet_data_list"):
            for row in NottyApi._as_list(related.get(source_key)):
                pet_id = row.get("pet_id") or row.get("id")
                if not matches_value(pet_id, (None, "")):
                    pet_rows.setdefault(str(pet_id), {}).update(row)
        return pet_rows

    async def _read_litter_pets(
        self, device_id: str, key: str, template: str, pet_rows: dict[str, JsonObject]
    ) -> list[JsonValue]:
        rows: list[JsonValue] = []
        for pet_id, pet_row in pet_rows.items():
            try:
                result = await self.request("GET", template.format(device_id=device_id, pet_id=pet_id))
            except NottyAuthError:
                raise
            except NottyApiError:
                _LOGGER.debug("Optional pet endpoint unavailable: %s", template)
                continue
            if not matches_value(result, (None, "")):
                row = {"pet_id": pet_id, "name": pet_row.get("name") or pet_row.get("alias"), key: result}
                rows.append({k: v for k, v in row.items() if not matches_value(v, (None, ""))})
        return rows

    async def litter_plans(self, device_id: str) -> list[JsonObject]:
        """Read the selected litter box's complete schedule list.

        Returns:
            Validated plan rows; an unavailable endpoint is never an empty list.
        """
        value = await self.request("GET", f"/device/litter_box/plans/{quote(device_id, safe='')}")
        return plan_rows(value)

    async def manage_litter_plan(self, device_id: str, action: str, data: JsonObject) -> JsonValue:
        """Validate current membership and send one explicitly targeted schedule write.

        Returns:
            The decoded server response.
        """
        rows = await self.litter_plans(device_id)
        payload = plan_payload(action, data, rows, device_id)
        if action == PLAN_OPEN:
            current = next(row for row in rows if row["plan_id"] == payload["plan_id"])
            if plan_enabled(current.get("open")) is payload["open"]:
                return None
        return await self.request("POST", LITTER_ACTION_ENDPOINTS[action], data=payload)

    async def litter_related_info(self, device_id: str) -> JsonObject:
        """Read optional litter-box endpoints and associated pet statistics.

        Returns:
            Successful optional responses and row counts.
        """
        related: JsonObject = {}
        for key, base_path in LITTER_READ_ENDPOINTS.items():
            related.update(await self._read_litter_related(device_id, key, base_path))
        pet_rows = self._related_pet_rows(related)
        for key, template in LITTER_PET_READ_ENDPOINTS.items():
            rows = await self._read_litter_pets(device_id, key, template, pet_rows)
            if rows:
                related.update(self._related_value(key, rows))
        return related

    async def pet_related_info(self, pet_id: str) -> JsonObject:
        """Pet related info.

        Returns:
            JsonObject: The resulting pet related info.

        Raises:
            NottyAuthError: When the cloud session is rejected.
        """
        related: JsonObject = {}
        for key, base_path in PET_READ_ENDPOINTS.items():
            try:
                result = await self.request("GET", base_path.format(pet_id=pet_id))
            except NottyAuthError:
                raise
            except NottyApiError:
                _LOGGER.debug("Optional NOTTY endpoint unavailable: %s", base_path)
                continue
            related[key] = result
            if isinstance(result, list):
                related[f"{key}_count"] = len(result)
            elif isinstance(result, dict):
                items = self._as_list(result)
                if items:
                    related[f"{key}_count"] = len(items)
        return related

    async def unread_message_count(self) -> int | None:
        """Unread message count.

        Returns:
            int | None: The resulting unread message count.
        """
        result = await self.request("GET", "/message/get_unread_count")
        return result if isinstance(result, int) else None

    async def save_pet(self, pet_id: str, data: JsonObject) -> JsonValue:
        """Save pet.

        Returns:
            JsonValue: The resulting save pet.
        """
        payload = {"pet_id": pet_id, **data}
        return await self.request("POST", "/pet/save", data=payload)

    async def associate_pet(self, device_id: str, pet_id: str, *, associate: bool = True) -> JsonValue:
        """Associate pet.

        Returns:
            JsonValue: The resulting associate pet.
        """
        return await self.request(
            "POST",
            "/device/associate_pet",
            data={"user_device_id": device_id, "pet_id": pet_id, "associate": associate},
        )

    async def save_pet_weight(self, pet_id: str, weight: float, current: JsonObject) -> JsonValue:
        """Save pet weight.

        Returns:
            JsonValue: The resulting save pet weight.

        Raises:
            NottyApiError: When the requested operation cannot be completed.
        """
        pet_devices = current.get("pet_devices")
        litter_device_id = self.pet_litter_device_id(current)
        has_litter_binding = bool(
            litter_device_id or current.get("bind_litter_box") or current.get("has_litter_box_data")
        )
        if has_litter_binding and not litter_device_id:
            msg = "Refusing to update cat weight without the current litter-box binding data"
            raise NottyApiError(msg)
        payload = {
            "name": current.get("name") or current.get("alias"),
            "birthday": current.get("birthday"),
            "breed_id": current.get("breed_id"),
            "sex": current.get("sex"),
            "weight": weight,
            "is_sterilization": current.get("is_sterilization"),
            "collar_id": current.get("collar_id") or 0,
            "image_path": current.get("image_path") or "",
        }
        if isinstance(pet_devices, list):
            payload["pet_devices"] = pet_devices
        for key in ("bind_litter_box", "bind_feeder", "bind_water_dispenser"):
            if key in current:
                payload[key] = current[key]
        result = await self.save_pet(
            pet_id, {key: value for key, value in payload.items() if not matches_value(value, (None, ""))}
        )
        if litter_device_id:
            await self.associate_pet(litter_device_id, pet_id, associate=True)
        return result

    async def command(self, device_id: str, action: JsonValue, device_type: str = "litter_box") -> JsonValue:
        """Send an APK-backed litter-box command.

        Returns:
            The decoded cloud response, which does not confirm a physical effect.

        Raises:
            NottyApiError: If the device kind or operation is unsupported.
        """
        if device_type != DEVICE_TYPE_LITTER_BOX:
            msg = "One-key commands are only established for litter boxes"
            raise NottyApiError(msg)
        return await self.request(
            "POST", "/device/litter_box/one_key", data={"user_device_id": device_id, "one_key": one_key_value(action)}
        )

    async def litter_action(self, device_id: str, action: str, data: JsonObject | None = None) -> JsonValue:
        """Litter action.

        Returns:
            JsonValue: The resulting litter action.

        Raises:
            NottyApiError: When the requested operation cannot be completed.
        """
        if action in PLAN_ACTIONS:
            return await self.manage_litter_plan(device_id, action, data or {})
        path = LITTER_ACTION_ENDPOINTS.get(action)
        if not path:
            msg = f"Unsupported litter box action: {action}"
            raise NottyApiError(msg)
        if action == ACTION_ONE_KEY:
            return await self.command(device_id, (data or {}).get(ACTION_ONE_KEY))
        if action == ACTION_SET_MODE:
            msg = "NOTTY mode changes remain disabled pending schedule prerequisites and live validation"
            raise NottyApiError(msg)
        settings = reminder_payload(action, data or {}) if action in REMINDER_CYCLE_FIELDS else (data or {})
        payload = {**settings, **self._device_payload(device_id)}
        if action == ACTION_SET_AUTO_DELAY:
            delay = payload.get("delay")
            if type(delay) is not int or not 1 <= delay <= MAX_DELAY_MINUTES:
                msg = "Automatic cleaning delay must be an integer from 1 to 15 minutes"
                raise NottyApiError(msg)
        return await self.request("POST", path, data=payload)
