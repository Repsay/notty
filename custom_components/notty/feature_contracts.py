"""Validation for APK-backed pet and account actions."""

from __future__ import annotations

from datetime import date, datetime
import math

from custom_components.notty.api import JsonObject, JsonValue, NottyApiError, plan_enabled

PET_EDIT_FIELDS = {"name", "birthday", "sex", "is_sterilization", "breed_id"}
PET_SAVE_FIELDS = (
    "image_path",
    "image_url",
    "name",
    "breed_id",
    "breed_name",
    "sex",
    "sex_name",
    "is_sterilization",
    "birthday",
    "weight",
    "collar_id",
    "is_default",
    "age",
    "shareds",
    "device_number",
)
MEMO_FIELDS = {"title", "content", "date", "remind"}
MAX_PET_NAME_UNITS = 10
MAX_MEMO_TITLE = 255
MAX_MEMO_CONTENT = 10000
SEX_NAMES = {1: "Male", 2: "Female"}
FIELD_NAME = "name"
FIELD_BIRTHDAY = "birthday"
FIELD_SEX = "sex"
FIELD_NEUTERED = "is_sterilization"
FIELD_BREED = "breed_id"
MIN_PET_NAME_UNITS = 2
TRUE_TEXT = "1"
NULL_CHAR = "\x00"


def identifier(value: JsonValue) -> int:
    """Accept positive decimal IDs without coercing Boolean or floating-point values.

    Returns:
        A physical, pet, category or memo integer ID.

    Raises:
        NottyApiError: If the identifier is missing or invalid.
    """
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    msg = "A positive numeric NOTTY ID is required"
    raise NottyApiError(msg)


def object_rows(value: JsonValue) -> list[JsonObject]:
    """Require an explicit list, optionally under the app's list/data field.

    Returns:
        Object records without treating a malformed response as an empty list.

    Raises:
        NottyApiError: If records are unavailable or malformed.
    """
    if isinstance(value, dict):
        value = value.get("list", value.get("data"))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        msg = "NOTTY returned an unreadable record list"
        raise NottyApiError(msg)
    return [row for row in value if isinstance(row, dict)]


def true_state(value: JsonValue) -> bool:
    """Recognize explicit ownership/on states.

    Returns:
        True only for Boolean true or integer/string one.
    """
    return value is True or (type(value) is int and value == 1) or (isinstance(value, str) and value == TRUE_TEXT)


def require_owner(profile: JsonObject) -> None:
    """Reject edits of shared pets without confirmed ownership.

    Raises:
        NottyApiError: If ownership is false or unknown.
    """
    if not true_state(profile.get("is_owner")):
        msg = "Only the NOTTY pet owner can edit this pet"
        raise NottyApiError(msg)


def _birthday(value: JsonValue) -> str:
    if not isinstance(value, str):
        msg = "Pet birthday must use YYYY-MM-DD"
        raise NottyApiError(msg)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        msg = "Pet birthday must be a valid YYYY-MM-DD date"
        raise NottyApiError(msg) from exc
    if parsed.isoformat() != value or parsed > datetime.now().astimezone().date():
        msg = "Pet birthday must be an existing calendar date"
        raise NottyApiError(msg)
    return value


def profile_changes(changes: JsonObject) -> JsonObject:
    """Validate the supported edit subset without inventing pet fields.

    Returns:
        Validated changes, preserving accepted name text.

    Raises:
        NottyApiError: If a field, enum, date or name is invalid.
    """
    if not changes or changes.keys() - PET_EDIT_FIELDS:
        msg = "Pet edits support name, birthday, sex, is_sterilization and breed_id"
        raise NottyApiError(msg)
    result = dict(changes)
    if FIELD_NAME in result:
        name = result["name"]
        if not isinstance(name, str) or not name.strip() or not name.isprintable():
            msg = "Pet name must contain printable text"
            raise NottyApiError(msg)
        if not MIN_PET_NAME_UNITS <= len(name.encode("utf-16-le")) // 2 <= MAX_PET_NAME_UNITS:
            msg = "Pet name must contain 2 to 10 UTF-16 units"
            raise NottyApiError(msg)
    if FIELD_BIRTHDAY in result:
        result["birthday"] = _birthday(result["birthday"])
    if FIELD_SEX in result and (type(result["sex"]) is not int or result["sex"] not in SEX_NAMES):
        msg = "Pet sex must be 1 (male) or 2 (female)"
        raise NottyApiError(msg)
    if FIELD_NEUTERED in result and type(result["is_sterilization"]) is not bool:
        msg = "Pet neutered state must be a Boolean"
        raise NottyApiError(msg)
    if FIELD_BREED in result:
        result["breed_id"] = identifier(result["breed_id"])
    return result


def profile_payload(pet_id: str, current: JsonObject, changes: JsonObject) -> JsonObject:
    """Preserve the complete known app profile and every device binding during edits.

    Returns:
        The APK pet/save fields with an explicit pet ID and unchanged binding list.

    Raises:
        NottyApiError: If ownership, identity, weight or binding metadata is unknown.
    """
    require_owner(current)
    if identifier(current.get("pet_id")) != identifier(pet_id):
        msg = "Pet profile identity mismatch"
        raise NottyApiError(msg)
    payload = {key: current[key] for key in PET_SAVE_FIELDS if key in current}
    weight = current.get("weight")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or not math.isfinite(weight) or weight <= 0:
        msg = "Pet editing requires the current positive profile weight"
        raise NottyApiError(msg)
    unit = current.get("weight_unit")
    if type(unit) is not int or unit not in {1, 2}:
        msg = "Pet editing requires a known current weight unit"
        raise NottyApiError(msg)
    devices = object_rows(current.get("pet_devices"))
    if any(plan_enabled(device.get("is_bind")) is None for device in devices):
        msg = "Pet editing requires known binding states for every listed device"
        raise NottyApiError(msg)
    bindings = [
        str(identifier(device.get("user_device_id"))) for device in devices if plan_enabled(device.get("is_bind"))
    ]
    payload.update({"pet_id": identifier(pet_id), "user_device_ids": ",".join(bindings), "weight_unit": unit})
    payload.update(profile_changes(changes))
    if not isinstance(payload.get("name"), str) or not payload["name"]:
        msg = "Pet editing requires the current pet name"
        raise NottyApiError(msg)
    _birthday(payload.get("birthday"))
    return payload


def memo_payload(pet_id: str, current: JsonObject, changes: JsonObject, *, create: bool) -> JsonObject:
    """Validate the app's text memo fields and raw NOTTY wall-clock date.

    Returns:
        A pet-scoped memo request; existing reminder metadata is preserved.

    Raises:
        NottyApiError: If fields or the date/identity are invalid.
    """
    if changes.keys() - MEMO_FIELDS or not changes:
        msg = "Memo changes support only title, content, date and remind"
        raise NottyApiError(msg)
    result = {key: current[key] for key in (*MEMO_FIELDS, "memo_id", "expired") if key in current}
    result.update(changes)
    for key, limit in (("title", MAX_MEMO_TITLE), ("content", MAX_MEMO_CONTENT)):
        text = result.get(key)
        if not isinstance(text, str) or not text.strip() or len(text) > limit or NULL_CHAR in text:
            msg = "Memo title and content must contain bounded, nonblank text"
            raise NottyApiError(msg)
        result[key] = text.strip()
    clock = result.get("date")
    try:
        valid_date = (
            isinstance(clock, str)
            and datetime.strptime(f"{clock} +0000", "%Y-%m-%d %H:%M %z").strftime("%Y-%m-%d %H:%M") == clock
        )
    except ValueError:
        valid_date = False
    if not valid_date or type(result.get("remind")) is not bool:
        msg = "Memo date must use YYYY-MM-DD HH:MM with an explicit Boolean reminder"
        raise NottyApiError(msg)
    result.update({"pet_id": identifier(pet_id), "memo_id": 0 if create else identifier(current.get("memo_id"))})
    return result
