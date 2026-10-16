"""Explicit feature writes for live validation; emptying is blocked at transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict, cast, override

from custom_components.notty.api import (
    JsonObject,
    JsonValue,
    NottyApi,
    NottyApiError,
    alias_payload,
    dnd_payload,
    plan_enabled,
)
from custom_components.notty.device_features import FirmwareApi, NotificationApi, clear_statistics, owned_litter
from custom_components.notty.device_timezone import change_with_readback
from custom_components.notty.feature_contracts import identifier, profile_changes
from custom_components.notty.pet_api import MemoApi, PetApi

POST = "POST"
GET = "GET"
ONE_KEY_PATH = "/device/litter_box/one_key"
SET_MODE = "set_mode"
SET_DND = "set_dnd"
SET_ALIAS = "set_alias"
SET_KEY = "set_key"
SET_DELAY = "set_auto_delay"
ASSOCIATE = "associate"
BLOCK = "block"
CREATE = "create"
UPDATE = "update"
ALIAS = "alias"
PETS = "pets"
NOTIFICATIONS = "notifications"


@dataclass
class Target:
    """An account-validated physical box and/or pet."""

    box: str
    pet: str
    device: JsonObject


class DndEdits(TypedDict, total=False):
    """Only writable DND fields, excluding builder clock/context parameters."""

    switch_dnd: JsonValue
    dnd_begin_time: JsonValue
    dnd_end_time: JsonValue


OPERATIONS = {
    "lock": {SET_KEY},
    "dnd": {SET_DND},
    "settings": {SET_DELAY, SET_MODE, "set_language"},
    "reminders": {
        "set_litter_remind",
        "set_garbage_bag_remind",
        "reset_litter_reminder",
        "reset_garbage_bag_reminder",
        "set_litter_reminder_days",
        "set_garbage_bag_reminder_days",
    },
    ALIAS: {SET_ALIAS},
    "commands": {"clean", "level"},
    "schedules": {"add_plan", "edit_plan", "open_plan", "delete_plan"},
    "timezone": {"change"},
    PETS: {UPDATE},
    "associations": {ASSOCIATE, "disassociate"},
    NOTIFICATIONS: {BLOCK, "unblock"},
    "memos": {CREATE, UPDATE},
    "firmware": {"install"},
    "statistics": {"clear"},
}


class ValidationApi(NottyApi):
    """Enforce the owner's no-empty rule even if a higher-level caller is wrong."""

    writes_enabled = False

    @override
    async def request(self, method: str, path: str, *, data: JsonObject | None = None) -> JsonValue:
        """Reject writes in read mode and all unrecognized motor operations.

        Returns:
            The normal API response.

        Raises:
            NottyApiError: If a write is disabled or could empty the litter box.
        """
        if method not in {GET, POST} or (method != GET and not self.writes_enabled):
            msg = "Validation writes require an explicit selected operation"
            raise NottyApiError(msg)
        if path.split("?", 1)[0].rstrip("/") == ONE_KEY_PATH and method == POST:
            operation = (data or {}).get("one_key")
            if type(operation) is not int or operation not in {1, 3}:
                msg = "Empty-litter and unknown motor commands are forbidden"
                raise NottyApiError(msg)
        return await super().request(method, path, data=data)


async def apply(api: ValidationApi, feature: str, target: Target, operation: str, changes: JsonObject) -> JsonValue:
    """Dispatch one allowlisted feature operation with account-scoped validation.

    Returns:
        Acknowledgement/readback, never evidence of a physical effect.

    Raises:
        NottyApiError: If the feature, operation or field set is unsupported.
    """
    require_operation(operation, OPERATIONS.get(feature, set()))
    if feature not in {"pets", "memos", "notifications", "login"}:
        await owned_litter(api, target.box)
    handlers = {
        "lock": setting,
        "dnd": setting,
        "settings": setting,
        "reminders": setting,
        "alias": alias,
        "commands": command,
        "schedules": schedule,
        "timezone": timezone,
        "pets": pet,
        "associations": association,
        "notifications": notification,
        "memos": memo,
        "firmware": firmware,
        "statistics": statistics,
    }
    handler = handlers.get(feature)
    if handler is None:
        msg = "This validation feature has no write operation"
        raise NottyApiError(msg)
    return await handler(api, target.box, target.pet, operation, changes)


def require_fields(changes: JsonObject, expected: set[str]) -> None:
    """Reject silent extra fields, missing values and target overrides.

    Raises:
        NottyApiError: If fields do not match the selected operation.
    """
    if set(changes) != expected:
        msg = "Write fields do not match the selected operation"
        raise NottyApiError(msg)


async def setting(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Validate and apply the integration's existing setting builders.

    Returns:
        Server acknowledgement.

    Raises:
        NottyApiError: If setting fields or values are unsupported.
    """
    fields = {"set_key": {"switch"}, "set_auto_delay": {"delay"}, SET_MODE: {"mode"}, "set_language": {"language"}}
    if operation == SET_DND:
        allowed = {"switch_dnd", "dnd_begin_time", "dnd_end_time"}
        if not changes or set(changes) - allowed:
            msg = "DND accepts switch_dnd and device-local start/end clock edits"
            raise NottyApiError(msg)
        payload = dnd_payload(await api.litter_info(box), **cast("DndEdits", changes))
    elif operation in api_reminders():
        payload = changes
    elif operation in fields:
        require_fields(changes, fields[operation])
        payload = changes
        if operation == SET_KEY and (type(changes["switch"]) is not int or changes["switch"] not in {0, 1}):
            msg = "Child lock requires integer switch 0 or 1"
            raise NottyApiError(msg)
        if operation == SET_DELAY and (await api.litter_info(box)).get("mode") != 1:
            msg = "Automatic delay requires Auto mode"
            raise NottyApiError(msg)
    else:
        msg = "Unsupported setting operation"
        raise NottyApiError(msg)
    return await api.litter_action(box, operation, payload)


def api_reminders() -> set[str]:
    """Known reminder write operations.

    Returns:
        Explicit reset, interval and toggle actions.
    """
    return {
        "set_litter_remind",
        "set_garbage_bag_remind",
        "reset_litter_reminder",
        "reset_garbage_bag_reminder",
        "set_litter_reminder_days",
        "set_garbage_bag_reminder_days",
    }


async def alias(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Set one cloud alias.

    Returns:
        Server acknowledgement.
    """
    require_fields(changes, {"alias"})
    require_operation(operation, {SET_ALIAS})
    return await api.set_device_alias(box, changes["alias"])


async def command(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Clean or level only; emptying is never a supported operation.

    Returns:
        Server acknowledgement, requiring physical observation.
    """
    require_fields(changes, set())
    require_operation(operation, {"clean", "level"})
    return await api.command(box, operation)


async def schedule(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Use the integration's fresh plan membership/payload validation.

    Returns:
        Server acknowledgement.
    """
    require_operation(operation, {"add_plan", "edit_plan", "open_plan", "delete_plan"})
    return await api.manage_litter_plan(box, operation, changes)


async def timezone(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Change one exact catalog ID with schedule snapshots.

    Returns:
        Before/after schedule readback.
    """
    require_operation(operation, {"change"})
    return await change_with_readback(api, box, changes)


async def pet(api: ValidationApi, _box: str, pet_id: str, operation: str, changes: JsonObject) -> JsonValue:
    """Edit an owned existing pet with all current bindings preserved.

    Returns:
        Fresh profile readback.
    """
    require_operation(operation, {"update"})
    return await PetApi(api).update(pet_id, changes)


async def association(api: ValidationApi, box: str, pet_id: str, operation: str, changes: JsonObject) -> JsonValue:
    """Change one association without affecting other pets.

    Returns:
        Fresh association rows.
    """
    require_operation(operation, {"associate", "disassociate"})
    require_fields(changes, set())
    return list(await PetApi(api).associate(box, pet_id, enabled=operation == ASSOCIATE))


async def notification(api: ValidationApi, _box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Block/unblock one current account category.

    Returns:
        Fresh category readback.
    """
    require_operation(operation, {"block", "unblock"})
    require_fields(changes, {"message_type_id"})
    return list(await NotificationApi(api).set_blocked(changes["message_type_id"], blocked=operation == BLOCK))


async def memo(api: ValidationApi, _box: str, pet_id: str, operation: str, changes: JsonObject) -> JsonValue:
    """Create or edit one text memo; no deletion contract is invented.

    Returns:
        The cloud acknowledgement.

    Raises:
        NottyApiError: If memo fields are malformed.
    """
    require_operation(operation, {"create", "update"})
    fields = {"fields"} if operation == CREATE else {"fields", "memo_id"}
    require_fields(changes, fields)
    values = changes["fields"]
    if not isinstance(values, dict):
        msg = "Memo fields must be an object"
        raise NottyApiError(msg)
    memo_id = identifier(changes["memo_id"]) if operation == UPDATE else None
    return await MemoApi(api).save(pet_id, values, memo_id=memo_id)


async def firmware(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Confirm only a fresh currently offered task.

    Returns:
        The requested version; completion needs later readback.
    """
    require_operation(operation, {"install"})
    require_fields(changes, set())
    return await FirmwareApi(api).install(box)


async def statistics(api: ValidationApi, box: str, _pet: str, operation: str, changes: JsonObject) -> JsonValue:
    """Clear selected-device statistics only through the explicit irreversible action.

    Returns:
        Server acknowledgement.
    """
    require_operation(operation, {"clear"})
    require_fields(changes, {"confirm_irreversible"})
    return await clear_statistics(api, box, confirmed=changes["confirm_irreversible"] is True)


def require_operation(operation: str, allowed: set[str]) -> None:
    """Reject unknown actions, particularly empty-litter aliases.

    Raises:
        NottyApiError: If the selected operation is outside this feature's scope.
    """
    if operation not in allowed:
        msg = "Unsupported validation operation; emptying is prohibited"
        raise NottyApiError(msg)


def restore_request(feature: str, operation: str, changes: JsonObject, before: JsonObject) -> tuple[str, JsonObject]:
    """Prepare restoration only where the exact original state is available.

    Returns:
        An operation and original values for supported reversible settings.

    Raises:
        NottyApiError: If automatic restoration cannot preserve the original state.
    """
    if feature in {"lock", "settings"} and operation in {SET_KEY, SET_DELAY, SET_MODE, "set_language"}:
        return _setting_restore(operation, changes, before)
    if feature == ALIAS:
        device = before.get("device")
        if isinstance(device, dict):
            value = device.get("alias")
            alias_payload(str(device.get("user_device_id")), value)
            return SET_ALIAS, {"alias": value}
    if feature == PETS:
        profile = before.get("profile")
        if isinstance(profile, dict) and all(key in profile for key in changes):
            return "update", profile_changes({key: profile[key] for key in changes})
    if feature == NOTIFICATIONS:
        restored = _notification_restore(changes, before)
        if restored is not None:
            return restored
    msg = "Automatic restoration is supported only for lock, mode/delay/language, alias, pet fields and notifications"
    raise NottyApiError(msg)


def _notification_restore(changes: JsonObject, before: JsonObject) -> tuple[str, JsonObject] | None:
    categories = before.get("categories")
    if isinstance(categories, list):
        for row in categories:
            if isinstance(row, dict) and row.get("message_type_id") == changes.get("message_type_id"):
                blocked = plan_enabled(row.get("blocked"))
                if blocked is not None:
                    return BLOCK if blocked else "unblock", changes
    return None


def _setting_restore(operation: str, changes: JsonObject, before: JsonObject) -> tuple[str, JsonObject]:
    info = before.get("info")
    if not isinstance(info, dict):
        info = {}
    keys = {SET_KEY: "switch_key", SET_DELAY: "auto_delay", SET_MODE: "mode", "set_language": "language"}
    field = {SET_KEY: "switch", SET_DELAY: "delay", SET_MODE: "mode", "set_language": "language"}[operation]
    require_fields(changes, {field})
    value = info.get(keys[operation])
    if type(value) is not int:
        msg = "Original setting must be a known integer before a roundtrip"
        raise NottyApiError(msg)
    ranges = {SET_KEY: {0, 1}, SET_DELAY: set(range(1, 16)), SET_MODE: {1, 2, 3}, "set_language": {0, 1, 2, 3}}
    if value not in ranges[operation]:
        msg = "Original setting is outside the restorable write range"
        raise NottyApiError(msg)
    return operation, {field: value}
