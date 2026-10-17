"""Litter-box maintenance and account notification operations from the APK."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from custom_components.notty.api import JsonObject, JsonValue, NottyApi, NottyApiError, plan_enabled
from custom_components.notty.feature_contracts import identifier, object_rows, true_state

SOURCE_PET = "pet"
LITTER_WORD = "litter"
SAND_WORD = "sand"
LITTER_MESSAGE_GROUP = 3
LITTER_PRODUCT_ID = 2
MAX_TASK_ID_LENGTH = 128
FIRMWARE_IDLE_STATUSES = {"", "SUCCEEDED", "FAILED", "CANCELED"}


async def owned_litter(api: NottyApi, device_id: str) -> JsonObject:
    """Require a current account-owned physical litter box for maintenance writes.

    Returns:
        The matching discovery metadata.

    Raises:
        NottyApiError: If ownership or supported device kind cannot be established.
    """
    selected = identifier(device_id)
    for row in await api.devices():
        if row.get("_notty_source") == SOURCE_PET:
            continue
        raw_id = row.get("user_device_id")
        if raw_id is None or identifier(raw_id) != selected:
            continue
        kind = " ".join(str(row.get(key, "")) for key in ("device_type", "type", "device_name", "product_name")).lower()
        if true_state(row.get("is_owner")) and (
            LITTER_WORD in kind or SAND_WORD in kind or row.get("device_id") == LITTER_PRODUCT_ID
        ):
            return row
    msg = "The action requires an account-owned physical NOTTY litter box"
    raise NottyApiError(msg)


class NotificationApi:
    """Account-wide NOTTY litter-box notification categories, independent of HA notifications."""

    def __init__(self, api: NottyApi) -> None:
        self.api = api

    async def categories(self) -> list[JsonObject]:
        """Read the APK's litter-box message group, not a physical device filter.

        Returns:
            Public category IDs, names and block states.

        Raises:
            NottyApiError: If category IDs or scope are malformed.
        """
        rows = object_rows(
            await self.api.request("GET", f"/message/get_type_block_stats_list?message_group_id={LITTER_MESSAGE_GROUP}")
        )
        seen: set[int] = set()
        result: list[JsonObject] = []
        for row in rows:
            category_id = identifier(row.get("message_type_id"))
            if category_id in seen or row.get("message_type_group_id") != LITTER_MESSAGE_GROUP:
                msg = "Notification category IDs or group scope are invalid"
                raise NottyApiError(msg)
            seen.add(category_id)
            result.append({key: row.get(key) for key in ("message_type_id", "message_type_name", "blocked")})
        return result

    async def set_blocked(self, category_id: JsonValue, *, blocked: bool) -> list[JsonObject]:
        """Change exactly one server-listed account category without retries.

        Returns:
            Fresh category readback.

        Raises:
            NottyApiError: If the category or its current state is unknown.
        """
        selected = identifier(category_id)
        rows = await self.categories()
        row = next((row for row in rows if identifier(row["message_type_id"]) == selected), None)
        if row is None or plan_enabled(row["blocked"]) is None:
            msg = "Select a notification category with a known current block state"
            raise NottyApiError(msg)
        if plan_enabled(row["blocked"]) is blocked:
            return rows
        await self.api.request(
            "POST", "/message/block_type", data={"message_type_id": row["message_type_id"], "block": blocked}
        )
        return await self.categories()


class FirmwareApi:
    """Fresh upgrade eligibility and the app's explicit task confirmation."""

    def __init__(self, api: NottyApi) -> None:
        self.api = api

    async def install(
        self,
        device_id: str,
        version: str | None = None,
        *,
        before_confirm: Callable[[str, JsonObject], Awaitable[None]] | None = None,
    ) -> str:
        """Confirm only the currently offered task for an owned litter box.

        Returns:
            The requested target version; installation completion requires later readback.

        Raises:
            NottyApiError: If no eligible task exists or the requested version differs.
        """
        device = await owned_litter(self.api, device_id)
        if device.get("status_id") == 0 or plan_enabled(device.get("online", device.get("is_online"))) is False:
            msg = "Firmware installation requires an online litter box"
            raise NottyApiError(msg)
        current = await self.api.request("GET", f"/device/check_upgrade/{identifier(device_id)}")
        if not isinstance(current, dict):
            msg = "Firmware metadata is unavailable"
            raise NottyApiError(msg)
        installed, target, task = current.get("src_version"), current.get("dest_version"), current.get("task_id")
        if not isinstance(installed, str) or not installed.strip():
            msg = "Firmware installation requires a known installed version"
            raise NottyApiError(msg)
        if not isinstance(target, str) or not target.strip() or target == installed or version not in {None, target}:
            msg = "Only the currently offered NOTTY firmware version can be installed"
            raise NottyApiError(msg)
        status = current.get("task_status")
        if not firmware_task_id(task) or not isinstance(status, str) or status not in FIRMWARE_IDLE_STATUSES:
            msg = "Firmware task is absent, busy or has an unknown status"
            raise NottyApiError(msg)
        if before_confirm is not None:
            await before_confirm(target, current)
        await self.api.request(
            "POST", "/device/confirm_upgrade", data={"user_device_id": identifier(device_id), "task_id": task}
        )
        return target


def firmware_task_id(value: JsonValue) -> bool:
    """Validate opaque task IDs without converting their server-provided type.

    Returns:
        Whether a positive integer or bounded printable task string is present.
    """
    return (type(value) is int and value > 0) or (
        isinstance(value, str) and bool(value.strip()) and value.isprintable() and len(value) <= MAX_TASK_ID_LENGTH
    )


async def clear_statistics(api: NottyApi, device_id: str, *, confirmed: bool) -> JsonObject:
    """Clear device statistics only after explicit irreversible-action acknowledgement.

    Returns:
        Acknowledgement metadata; affected sensors refresh through the coordinator.

    Raises:
        NottyApiError: If confirmation or ownership is absent.
    """
    if confirmed is not True:
        msg = "Statistics deletion requires confirm_irreversible: true"
        raise NottyApiError(msg)
    await owned_litter(api, device_id)
    await api.request("POST", f"/device/clear_statistics/{identifier(device_id)}", data={})
    return {"status": "write_acknowledged", "scope": "selected_device_statistics", "reversible": False}
