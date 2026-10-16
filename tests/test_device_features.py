"""Account scope, firmware task eligibility and irreversible maintenance contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.notty.api import JsonObject, JsonValue, NottyApi, NottyApiError
from custom_components.notty.device_features import FirmwareApi, NotificationApi, clear_statistics

BOX_ID = "123"
METHOD_GET = "GET"
METHOD_POST = "POST"
FIELD_DEVICE_ID = "user_device_id"
FIELD_OWNER = "is_owner"
FIELD_DEVICES = "pet_devices"
BREED_ID = 9
BREED_NAME = "Synthetic breed"
RESET_CODE = 3
TARGET_VERSION = "0.9.9"
UPGRADE: JsonObject = {"src_version": "0.9.8", "dest_version": TARGET_VERSION, "task_id": "task-7", "task_status": ""}
CATEGORIES: list[JsonValue] = [
    {"message_type_id": 12, "message_type_name": "Cleaning", "message_type_group_id": 3, "blocked": False},
    {"message_type_id": 13, "message_type_name": "Fault", "message_type_group_id": 3, "blocked": True},
]


def client() -> NottyApi:
    """Construct an owned litter-box client without any live transport.

    Returns:
        The isolated API client.
    """
    api = NottyApi(MagicMock())
    api.devices = AsyncMock(
        return_value=[{"user_device_id": 123, "device_type": "litter_box", "is_owner": True, "status_id": 1}]
    )
    api.request = AsyncMock()
    return api


async def test_notifications_are_account_group_reads_and_boolean_category_writes() -> None:
    """A physical ID never enters the account-level category request."""
    api = client()
    api.request.side_effect = [CATEGORIES, {}, CATEGORIES]
    await NotificationApi(api).set_blocked(12, blocked=True)
    api.request.assert_any_await("GET", "/message/get_type_block_stats_list?message_group_id=3")
    api.request.assert_any_await("POST", "/message/block_type", data={"message_type_id": 12, "block": True})
    assert all(FIELD_DEVICE_ID not in call.kwargs.get("data", {}) for call in api.request.await_args_list)


async def test_notification_same_state_does_not_write() -> None:
    """An already blocked category is a read-only no-op."""
    api = client()
    api.request.return_value = CATEGORIES
    await NotificationApi(api).set_blocked(13, blocked=True)
    api.request.assert_awaited_once_with("GET", "/message/get_type_block_stats_list?message_group_id=3")


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"message_type_id": 12, "message_type_group_id": 4, "blocked": False}],
        CATEGORIES + CATEGORIES,
        [{"message_type_id": 12, "message_type_group_id": 3, "blocked": None}],
    ],
)
async def test_unknown_notification_scope_ids_and_states_never_write(rows: JsonValue) -> None:
    """Reject foreign categories, ambiguous IDs and missing block-state readback."""
    api = client()
    api.request.return_value = rows
    with pytest.raises(NottyApiError):
        await NotificationApi(api).set_blocked(12, blocked=True)
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)


@pytest.mark.parametrize("task", ["task-7", 7])
async def test_firmware_confirmation_preserves_native_task_id_type(task: JsonValue) -> None:
    """The APK confirms the fresh task using only task_id and integer physical ID."""
    api = client()
    api.request.side_effect = [{**UPGRADE, "task_id": task}, {}]
    assert await FirmwareApi(api).install(BOX_ID) == TARGET_VERSION
    api.request.assert_awaited_with("POST", "/device/confirm_upgrade", data={"task_id": task, "user_device_id": 123})


@pytest.mark.parametrize(
    "changes",
    [
        {"dest_version": ""},
        {"dest_version": "0.9.8"},
        {"dest_version": None},
        {"src_version": None},
        {"task_id": None},
        {"task_id": ""},
        {"task_id": True},
        {"task_id": -1},
        {"task_status": "RUNNING"},
        {"task_status": "unknown"},
        {"task_status": []},
    ],
)
async def test_invalid_or_busy_firmware_tasks_never_write(changes: JsonObject) -> None:
    """Unknown state must not be treated as permission to start an upgrade."""
    api = client()
    api.request.return_value = {**UPGRADE, **changes}
    with pytest.raises(NottyApiError):
        await FirmwareApi(api).install(BOX_ID)
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)


async def test_firmware_refuses_arbitrary_version_and_never_retries_rejection() -> None:
    """Users cannot request a non-offered version or reuse another firmware task."""
    api = client()
    api.request.return_value = UPGRADE
    with pytest.raises(NottyApiError):
        await FirmwareApi(api).install(BOX_ID, "some-other-version")
    api.request.reset_mock()
    api.request.side_effect = [UPGRADE, NottyApiError("rejected")]
    with pytest.raises(NottyApiError):
        await FirmwareApi(api).install(BOX_ID)
    posts = [call for call in api.request.await_args_list if call.args[0] == METHOD_POST]
    assert len(posts) == 1


@pytest.mark.parametrize(
    "device",
    [
        {"user_device_id": 123, "device_type": "litter_box", "is_owner": False},
        {"user_device_id": 123, "device_type": "feeder", "is_owner": True},
        {"user_device_id": 123, "device_type": "litter_box", "is_owner": True, "_notty_source": "pet"},
        {"user_device_id": 123, "device_type": "litter_box", "is_owner": True, "status_id": 0},
    ],
)
async def test_firmware_requires_owned_online_physical_litter_box(device: JsonObject) -> None:
    """Shared devices, pets, feeders and explicit offline readback cannot install."""
    api = client()
    api.devices.return_value = [device]
    with pytest.raises(NottyApiError):
        await FirmwareApi(api).install(BOX_ID)
    api.request.assert_not_awaited()


async def test_statistics_reset_requires_confirmation_then_posts_empty_body_to_scoped_path() -> None:
    """The APK places the device ID in the path, not a guessed JSON body."""
    api = client()
    with pytest.raises(NottyApiError):
        await clear_statistics(api, BOX_ID, confirmed=False)
    api.devices.assert_not_awaited()
    api.request.assert_not_awaited()
    await clear_statistics(api, BOX_ID, confirmed=True)
    api.request.assert_awaited_once_with("POST", "/device/clear_statistics/123", data={})


@pytest.mark.parametrize("mode", [0, 4, True, 1.0, "2"])
async def test_unknown_mode_values_never_write(mode: JsonValue) -> None:
    """Only the traced integer modes are accepted."""
    api = client()
    with pytest.raises(NottyApiError):
        await api.litter_action(BOX_ID, "set_mode", {"mode": mode})
    api.request.assert_not_awaited()


async def test_scheduled_mode_requires_a_fresh_enabled_plan() -> None:
    """An empty/disabled schedule list cannot silently create scheduled mode."""
    api = client()
    api.litter_info = AsyncMock(return_value={"user_device_id": 123, "mode": 1})
    api.litter_plans = AsyncMock(return_value=[{"plan_id": 1, "open": False}])
    with pytest.raises(NottyApiError, match="enabled cleaning plan"):
        await api.litter_action(BOX_ID, "set_mode", {"mode": 2})
    api.request.assert_not_awaited()
    api.litter_plans.return_value = [{"plan_id": 1, "open": True}]
    await api.litter_action(BOX_ID, "set_mode", {"mode": 2})
    api.request.assert_awaited_once_with("POST", "/device/litter_box/set_mode", data={"user_device_id": 123, "mode": 2})


@pytest.mark.parametrize(
    ("action", "cycle_field", "enabled_field", "cycle"),
    [
        ("reset_litter_reminder", "default_remaining_days", "open_litter_remind", 20),
        ("reset_garbage_bag_reminder", "garbage_bag_cycle_time", "open_garbagebag_remind", 7),
    ],
)
async def test_reminder_reset_uses_three_and_preserves_the_configured_cycle(
    action: str, cycle_field: str, enabled_field: str, cycle: int
) -> None:
    """An explicit reset is distinct from disable and interval editing."""
    api = client()
    api.litter_info = AsyncMock(return_value={cycle_field: cycle, enabled_field: True})
    await api.litter_action(BOX_ID, action, {"cycle_time": cycle})
    post = api.request.await_args
    assert post.kwargs["data"]["action"] == RESET_CODE
    assert post.kwargs["data"]["cycle_time"] == cycle
    api.litter_info.return_value[enabled_field] = False
    api.request.reset_mock()
    with pytest.raises(NottyApiError):
        await api.litter_action(BOX_ID, action, {"cycle_time": cycle})
    api.request.assert_not_awaited()
