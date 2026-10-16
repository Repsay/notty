"""Schedule contracts from APK 1.1.30, with synthetic plan IDs and clocks."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.notty.api import NottyApi, NottyApiError, plan_enabled, plan_id, plan_payload, plan_rows
from custom_components.notty.coordinator import litter_related_summary
from custom_components.notty.schedule import schedule_request, schedule_response
from tests.test_lifecycle import setup

CONTRACT = json.loads((Path(__file__).parent / "fixtures/apk_litter_plans.json").read_text())
PLAN = {"plan_id": 81, "time": "07:00", "open": False, "quantity": 1, "plan_type_id": 1}
EXPECTED_FALSE_COUNT = 1
EXPECTED_EDIT = "edit_plan"
EXPECTED_OPEN = "open_plan"
EXPECTED_CREATE = "create"
PRIVATE_VALUE = "private-value"


@pytest.mark.parametrize("fixture", CONTRACT["requests"], ids=[row["action"] for row in CONTRACT["requests"]])
async def test_schedule_requests_match_app_contract(fixture: dict[str, object]) -> None:
    """Target an existing plan using its native ID and only the traced write fields."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(side_effect=[[PLAN.copy()], {}])
    original = PLAN.copy()
    await api.litter_action("synthetic-box", fixture["action"], fixture["input"])
    assert api.request.await_args_list[0].args == ("GET", CONTRACT["read"]["path"])
    api.request.assert_awaited_with("POST", f"/device/litter_box/{fixture['action']}", data=fixture["payload"])
    assert original == PLAN


@pytest.mark.parametrize("clock", ["00:00", "23:59", "02:30"])
@pytest.mark.parametrize("instant", [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)])
def test_schedule_clock_is_not_shifted_by_season_or_ha_zone(clock: str, instant: datetime) -> None:
    """No unverified DND or fixed-offset conversion changes schedule input."""
    with freeze_time(instant):
        assert plan_payload("add_plan", {"time": clock}, [], "synthetic-box") == {
            "time": clock,
            "quantity": 1,
            "user_device_id": "synthetic-box",
        }


@pytest.mark.parametrize(
    "clock",
    [
        None,
        "7:00",
        "24:00",
        "12:60",
        "12:00:00",
        "12:00Z",
        "12:00+02:00",
        " 12:00",
        "\uff11\uff12:\uff10\uff10",
        1200,
        {},
    ],
)
def test_invalid_clock_is_rejected(clock: object) -> None:
    """Accept precisely the app's HH:MM string format."""
    with pytest.raises(NottyApiError, match="HH:MM"):
        plan_payload("add_plan", {"time": clock}, [], "synthetic-box")


@pytest.mark.parametrize("identifier", [None, True, False, 0, -1, "", "0", "-1", " 81", "81\n", {}, [], 81.0])
def test_invalid_plan_ids_are_rejected(identifier: object) -> None:
    """A plan must be explicitly identified without permissive coercion."""
    with pytest.raises(NottyApiError, match="plan_id"):
        plan_id(identifier)


@pytest.mark.parametrize("value", [{}, None, [None], [{}], [PLAN, PLAN.copy()]])
async def test_unknown_or_ambiguous_plan_list_prevents_writes(value: object) -> None:
    """An unavailable or malformed response must never mean an empty plan list."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(return_value=value)
    with pytest.raises(NottyApiError):
        await api.manage_litter_plan("synthetic-box", "add_plan", {"time": "06:30"})
    assert api.request.await_count == 1


@pytest.mark.parametrize("action", ["edit_plan", "delete_plan", "open_plan"])
async def test_plan_from_another_box_is_never_modified(action: str) -> None:
    """Fresh selected-box membership is required even if the ID is syntactically valid."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(return_value=[PLAN.copy()])
    fields = {"plan_id": "other-plan"}
    if action == EXPECTED_EDIT:
        fields["time"] = "06:30"
    if action == EXPECTED_OPEN:
        fields["open"] = True
    with pytest.raises(NottyApiError, match="does not belong"):
        await api.manage_litter_plan("synthetic-box", action, fields)
    api.request.assert_awaited_once_with("GET", "/device/litter_box/plans/synthetic-box")


async def test_new_plan_limit_counts_disabled_plans() -> None:
    """The APK limits the complete list to ten, including disabled entries."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(return_value=[{**PLAN, "plan_id": index + 1} for index in range(10)])
    with pytest.raises(NottyApiError, match="at most ten"):
        await api.manage_litter_plan("synthetic-box", "add_plan", {"time": "06:30"})
    assert api.request.await_count == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"time": "06:30", "weekdays": [1]},
        {"time": "06:30", "open": False},
        {"time": "06:30", "user_device_id": "other"},
        {"time": "06:30", "quantity": 5},
    ],
)
def test_create_rejects_untraced_or_overriding_fields(fields: dict[str, object]) -> None:
    """Do not pretend the fixed-clock app request supports arbitrary recurrence."""
    with pytest.raises(NottyApiError, match="requires exactly"):
        plan_payload("add_plan", fields, [], "synthetic-box")


@pytest.mark.parametrize("state", [0, 1, "true", "false", None, {}])
def test_toggle_write_requires_boolean(state: object) -> None:
    """Read-side 0/1 compatibility cannot silently change the write-side type."""
    with pytest.raises(NottyApiError, match="Boolean"):
        plan_payload("open_plan", {"plan_id": 81, "open": state}, [PLAN.copy()], "synthetic-box")


@pytest.mark.parametrize("enabled", [False, True])
async def test_toggle_is_idempotent_and_preserves_other_fields(*, enabled: bool) -> None:
    """Do not rewrite a matching enable state or send unrelated time/quantity fields."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(return_value=[{**PLAN, "open": enabled}])
    await api.manage_litter_plan("synthetic-box", "open_plan", {"plan_id": 81, "open": enabled})
    assert api.request.await_count == 1


@pytest.mark.parametrize("changes", [{"quantity": 2}, {"quantity": True}, {"plan_type_id": 2}, {"plan_type_id": "1"}])
def test_edit_does_not_reinterpret_other_plan_types(changes: dict[str, object]) -> None:
    """Unknown recurrence/quantity is not overwritten by the litter-box default."""
    with pytest.raises(NottyApiError, match="unsupported schedule"):
        plan_payload("edit_plan", {"plan_id": 81, "time": "06:30"}, [{**PLAN, **changes}], "synthetic-box")


def test_disabled_string_states_are_not_counted_as_enabled() -> None:
    """String '0'/'false' are false, unlike bool(nonempty_string)."""
    rows = [{"open": value} for value in ("0", "false", False, 0, "1", "unknown")]
    summary = litter_related_summary({"plans": rows})
    assert summary["enabled_plans_count"] == EXPECTED_FALSE_COUNT
    assert plan_enabled({}) is None


@pytest.mark.parametrize(
    ("operation", "fields", "expected"),
    [
        ("list", {}, ("list", {})),
        ("create", {"time": "06:30"}, ("add_plan", {"time": "06:30"})),
        ("update", {"plan_id": 81, "time": "06:30"}, ("edit_plan", {"plan_id": 81, "time": "06:30"})),
        ("enable", {"plan_id": 81}, ("open_plan", {"plan_id": 81, "open": True})),
        ("disable", {"plan_id": 81}, ("open_plan", {"plan_id": 81, "open": False})),
        ("delete", {"plan_id": 81}, ("delete_plan", {"plan_id": 81})),
    ],
)
def test_ha_operation_translation(operation: str, fields: dict[str, object], expected: object) -> None:
    """Keep public operations distinct without accepting mixed-purpose writes."""
    assert schedule_request(operation, fields) == expected


@pytest.mark.parametrize(
    ("operation", "fields"),
    [("delete", {}), ("list", {"plan_id": 81}), ("enable", {"plan_id": 81, "time": "06:30"}), ("unknown", {})],
)
def test_invalid_operation_fields_cannot_be_submitted(operation: str, fields: dict[str, object]) -> None:
    """Omitting a deletion target or mixing fields never implies a bulk operation."""
    with pytest.raises(NottyApiError, match="fields"):
        schedule_request(operation, fields)


async def test_schedule_listing_response_is_scoped_and_read_only(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Users can retrieve IDs for explicit targeting without backend credentials."""
    runtime_api.litter_plans.return_value = [{**PLAN, "token": "private-value"}]
    await setup(hass)
    result = await hass.services.async_call(
        "notty",
        "litter_box_schedule",
        {"user_device_id": "box-1", "operation": "list"},
        blocking=True,
        return_response=True,
    )
    assert result == schedule_response([PLAN.copy()], None)
    runtime_api.manage_litter_plan.assert_not_awaited()
    runtime_api.litter_plans.assert_awaited_once_with("box-1")
    assert PRIVATE_VALUE not in json.dumps(result)


@pytest.mark.parametrize("operation", ["create", "update", "enable", "disable", "delete"])
async def test_schedule_service_mutates_refreshes_and_reads_back(
    hass: HomeAssistant, runtime_api: MagicMock, operation: str
) -> None:
    """Exercise every HA action against the selected physical box."""
    runtime_api.litter_plans.return_value = [PLAN.copy()]
    entry = await setup(hass)
    fields = {} if operation == EXPECTED_CREATE else {"plan_id": 81}
    if operation in {"create", "update"}:
        fields["time"] = "06:30"
    result = await hass.services.async_call(
        "notty",
        "litter_box_schedule",
        {"user_device_id": "box-1", "operation": operation, **fields},
        blocking=True,
        return_response=True,
    )
    action, payload = schedule_request(operation, fields)
    runtime_api.manage_litter_plan.assert_awaited_once_with("box-1", action, payload)
    assert result["plans"] == [PLAN]
    assert entry.runtime_data.last_update_success


@pytest.mark.parametrize("device", ["pet_cat-1", "unknown"])
async def test_invalid_schedule_device_prevents_api_calls(
    hass: HomeAssistant, runtime_api: MagicMock, device: str
) -> None:
    """Account pets and unknown devices cannot become schedule targets."""
    await setup(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "notty",
            "litter_box_schedule",
            {"user_device_id": device, "operation": "delete", "plan_id": 81},
            blocking=True,
        )
    runtime_api.manage_litter_plan.assert_not_awaited()
    runtime_api.litter_plans.assert_not_awaited()


async def test_failed_write_does_not_read_back_or_retry(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A rejected request must surface once without silently repeating it."""
    await setup(hass)
    runtime_api.manage_litter_plan.side_effect = NottyApiError("rejected")
    with pytest.raises(HomeAssistantError, match="rejected"):
        await hass.services.async_call(
            "notty",
            "litter_box_schedule",
            {"user_device_id": "box-1", "operation": "delete", "plan_id": 81},
            blocking=True,
        )
    runtime_api.manage_litter_plan.assert_awaited_once()
    runtime_api.litter_plans.assert_not_awaited()


@pytest.mark.usefixtures("runtime_api")
async def test_schedule_service_unloads_with_last_entry(hass: HomeAssistant) -> None:
    """Unloading the integration removes its schedule management service."""
    entry = await setup(hass)
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("notty", "litter_box_schedule")


def test_plan_rows_preserve_id_type_and_unknown_read_fields() -> None:
    """Do not rebuild plan identity or mutate raw response dictionaries."""
    rows = [{**PLAN, "opaque_field": {"future": True}}]
    before = json.dumps(rows)
    assert plan_rows(rows) == rows
    assert json.dumps(rows) == before
