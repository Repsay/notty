"""Reminder contracts independently traced from NOTTY 1.1.30 ARM64 callers."""

from __future__ import annotations

from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.notty.api import NottyApi, NottyApiError, reminder_payload
from tests.test_lifecycle import setup


class Reminder(NamedTuple):
    """Independent expected endpoint, state and interval metadata."""

    action: str
    field: str
    cycle_key: str
    entity: str
    cycle: int


ACTION_LITTER = "set_litter_remind"
RESET_LITTER = "reset_litter_reminder"
DISABLE = 2
REMINDERS = [
    Reminder(ACTION_LITTER, "open_litter_remind", "default_remaining_days", "litter_renewal_reminder", 20),
    Reminder("set_garbage_bag_remind", "open_garbagebag_remind", "garbage_bag_cycle_time", "trash_bag_reminder", 7),
]
EXPECTED_UNKNOWN = "unknown"
EXPECTED_OFF = "off"
EXPECTED_ON = "on"
EXPECTED_UNAVAILABLE = "unavailable"
EXPECTED_30_DAYS = "30 days"


@pytest.mark.parametrize("reminder", REMINDERS)
@pytest.mark.parametrize("operation", [1, 2])
async def test_wire_contract(reminder: Reminder, operation: int) -> None:
    """Match the app's action and cycle fields without leaking read-state fields."""
    action, _, _, _, cycle = reminder
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    data = {"action": operation, "cycle_time": cycle, "open_litter_remind": 1, "remaining_days": 1}
    before = data.copy()
    await api.litter_action("box-1", action, data)
    expected = {"action": operation, "user_device_id": "box-1", "device_id": "box-1"}
    expected["cycle_time"] = cycle
    endpoint = (
        "/device/litter_box/set_litter_remind"
        if action == ACTION_LITTER
        else "/device/litter_box/set_garbage_bag_remind"
    )
    api.request.assert_awaited_once_with("POST", endpoint, data=expected)
    assert data == before


@pytest.mark.parametrize(
    "action", ["reset_litter_reminder", "reset_garbage_bag_reminder", "set_garbage_bag_reminder_days"]
)
async def test_reminder_edits_without_current_state_do_not_write(action: str) -> None:
    """Observed action 2 disables reminders and must not be reused for reset/update."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    api.litter_info = AsyncMock(return_value={})
    with pytest.raises(NottyApiError, match="enabled reminder"):
        await api.litter_action("box-1", action, {"cycle_time": 10})
    api.request.assert_not_awaited()


async def test_litter_interval_action_three_wire_contract() -> None:
    """Owner observed action 3 changing enabled litter interval from 30 to 29."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    api.litter_info = AsyncMock(return_value={"open_litter_remind": True, "default_remaining_days": 30})
    await api.litter_action("box-1", "set_litter_reminder_days", {"cycle_time": 29})
    api.request.assert_awaited_once_with(
        "POST",
        "/device/litter_box/set_litter_remind",
        data={"action": 3, "cycle_time": 29, "user_device_id": "box-1", "device_id": "box-1"},
    )


@pytest.mark.parametrize("action", [1, 2, 0, "3", None, True])
def test_litter_interval_action_rejects_other_codes(action: object) -> None:
    """An interval adjustment must not accidentally enable or disable a reminder."""
    with pytest.raises(NottyApiError, match="action=3"):
        reminder_payload("set_litter_reminder_days", {"action": action, "cycle_time": 29})


@pytest.mark.parametrize("cycle", [None, True, False, 4, 31, 3.5, "unknown", {}, []])
async def test_litter_interval_invalid_cycle_does_not_write(cycle: object) -> None:
    """Reject all unverified or invalid intervals before an HTTP request."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="cycle_time"):
        await api.litter_action("box-1", "set_litter_reminder_days", {"cycle_time": cycle})
    api.request.assert_not_awaited()


@pytest.mark.parametrize("cycle", [None, True, False, 1, 31, 3.5, "unknown", {}, []])
async def test_invalid_interval_never_writes(cycle: object) -> None:
    """Refuse guessed defaults or remaining-day counters as interval replacements."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="cycle_time"):
        await api.litter_action("box-1", "set_litter_remind", {"action": 1, "cycle_time": cycle})
    api.request.assert_not_awaited()


@pytest.mark.parametrize("operation", [None, True, False, 0, 3, 4, "1", {}, []])
def test_invalid_operation_is_rejected(operation: object) -> None:
    """Do not confuse booleans or the read state with action enums."""
    with pytest.raises(NottyApiError, match="Reminder action"):
        reminder_payload("set_litter_remind", {"action": operation, "cycle_time": 20})


@pytest.mark.parametrize(
    ("action", "minimum", "maximum"), [("set_litter_remind", 5, 30), ("set_garbage_bag_remind", 2, 15)]
)
@pytest.mark.parametrize("operation", [1, 2])
def test_interval_boundaries(action: str, minimum: int, maximum: int, operation: int) -> None:
    """The server requires a valid cycle for both enable and disable."""
    for days in (minimum, maximum):
        assert reminder_payload(action, {"action": operation, "cycle_time": str(days)}) == {
            "action": operation,
            "cycle_time": days,
        }
    for days in (minimum - 1, maximum + 1):
        with pytest.raises(NottyApiError, match="cycle_time"):
            reminder_payload(action, {"action": operation, "cycle_time": days})


@pytest.mark.parametrize("reminder", REMINDERS)
@pytest.mark.parametrize("transition", [("turn_on", 0, 1), ("turn_off", 1, 2)])
async def test_switch_preserves_interval_and_refreshes(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder, transition: tuple[str, int, int]
) -> None:
    """Exercise HA services and leave timer settings untouched when disabling."""
    action, field, cycle_key, entity, cycle = reminder
    service, initial, operation = transition
    runtime_api.device_info.return_value.update({field: initial, cycle_key: cycle, "remaining_days": 1})
    entry = await setup(hass)
    before = runtime_api.device_info.return_value.copy()
    entity_id = f"switch.test_box_{entity}"
    assert hass.states.get(entity_id).state == (EXPECTED_ON if initial else EXPECTED_OFF)
    expected = {"action": operation, "cycle_time": cycle}
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)
    runtime_api.litter_action.assert_awaited_once_with("box-1", action, expected)
    assert runtime_api.device_info.return_value == before
    assert entry.runtime_data.last_update_success


@pytest.mark.parametrize("reminder", REMINDERS)
@pytest.mark.parametrize(("initial", "service"), [(1, "turn_on"), (0, "turn_off")])
async def test_repeated_switch_command_does_not_restart_reminder(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder, initial: int, service: str
) -> None:
    """An unchanged switch must not restart or otherwise alter the countdown."""
    _, field, cycle_key, entity, cycle = reminder
    runtime_api.device_info.return_value.update({field: initial, cycle_key: cycle})
    await setup(hass)
    await hass.services.async_call("switch", service, {"entity_id": f"switch.test_box_{entity}"}, blocking=True)
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("reminder", REMINDERS)
async def test_enabling_requires_configured_interval(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder
) -> None:
    """A remaining-day measurement is never substituted for a missing interval."""
    _, field, _, entity, _ = reminder
    runtime_api.device_info.return_value.update({field: 0, "remaining_days": 12})
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="cycle_time"):
        await hass.services.async_call("switch", "turn_on", {"entity_id": f"switch.test_box_{entity}"}, blocking=True)
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("reminder", REMINDERS)
async def test_disabling_requires_configured_interval(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder
) -> None:
    """Both live endpoints reject the disable request without cycle_time."""
    _, field, _, entity, _ = reminder
    runtime_api.device_info.return_value.update({field: 1})
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="cycle_time"):
        await hass.services.async_call("switch", "turn_off", {"entity_id": f"switch.test_box_{entity}"}, blocking=True)
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("reminder", REMINDERS)
@pytest.mark.parametrize("service", ["turn_on", "turn_off"])
async def test_unknown_state_cannot_be_written(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder, service: str
) -> None:
    """Missing or novel enable enums are not silently treated as off."""
    _, field, cycle_key, entity, cycle = reminder
    runtime_api.device_info.return_value.update({field: 8, cycle_key: cycle})
    await setup(hass)
    assert hass.states.get(f"switch.test_box_{entity}").state == EXPECTED_UNKNOWN
    with pytest.raises(HomeAssistantError, match="unknown current state"):
        await hass.services.async_call("switch", service, {"entity_id": f"switch.test_box_{entity}"}, blocking=True)
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize(
    ("button", "cycle_key", "cycle"),
    [
        ("reset_litter_reminder", "default_remaining_days", 20),
        ("reset_garbage_bag_reminder", "garbage_bag_cycle_time", 7),
    ],
)
async def test_reset_button_uses_action_three_and_the_configured_cycle(
    hass: HomeAssistant, runtime_api: MagicMock, button: str, cycle_key: str, cycle: int
) -> None:
    """Action 2 disables the device; never use it for a reset button."""
    runtime_api.device_info.return_value[cycle_key] = cycle
    runtime_api.device_info.return_value[
        "open_litter_remind" if button == RESET_LITTER else "open_garbagebag_remind"
    ] = True
    await setup(hass)
    entity_name = "reset_litter_renewal_reminder" if button == RESET_LITTER else "reset_trash_bag_reminder"
    await hass.services.async_call("button", "press", {"entity_id": f"button.test_box_{entity_name}"}, blocking=True)
    runtime_api.litter_action.assert_awaited_once_with("box-1", button, {"action": 3, "cycle_time": cycle})
    runtime_api.endpoint_action.assert_not_awaited()


@pytest.mark.usefixtures("runtime_api")
async def test_unsupported_device_has_no_reminder_switch(hass: HomeAssistant) -> None:
    """Do not create controls for fields the device does not report."""
    await setup(hass)
    assert hass.states.get("switch.test_box_litter_renewal_reminder") is None
    assert hass.states.get("switch.test_box_trash_bag_reminder") is None


async def test_litter_interval_select_changes_enabled_reminder(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """HA interval select uses the verified action-3 mapping."""
    runtime_api.device_info.return_value.update({
        "open_litter_remind": True,
        "default_remaining_days": 30,
        "remaining_days": 30,
    })
    await setup(hass)
    entity_id = "select.test_box_litter_renewal_reminder_interval"
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == EXPECTED_30_DAYS
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "29 days"}, blocking=True
    )
    runtime_api.litter_action.assert_awaited_once_with("box-1", "set_litter_reminder_days", {"cycle_time": 29})


async def test_litter_interval_select_noop_does_not_reset_countdown(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """Never resend unchanged cycle; action 3 same-cycle reset is unverified."""
    runtime_api.device_info.return_value.update({
        "open_litter_remind": True,
        "default_remaining_days": 30,
        "remaining_days": 21,
    })
    await setup(hass)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.test_box_litter_renewal_reminder_interval", "option": "30 days"},
        blocking=True,
    )
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("enabled", [False, None, 8])
async def test_litter_interval_select_unavailable_when_not_enabled(
    hass: HomeAssistant, runtime_api: MagicMock, enabled: object
) -> None:
    """Do not send untested action-3 writes on disabled or unknown states."""
    runtime_api.device_info.return_value.update({"open_litter_remind": enabled, "default_remaining_days": 30})
    await setup(hass)
    entity_id = "select.test_box_litter_renewal_reminder_interval"
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == EXPECTED_UNAVAILABLE
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "29 days"}, blocking=True
    )
    runtime_api.litter_action.assert_not_awaited()


async def test_generic_litter_interval_action_three(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Generic service also validates active state before an interval write."""
    runtime_api.device_info.return_value.update({"open_litter_remind": True, "default_remaining_days": 30})
    await setup(hass)
    await hass.services.async_call(
        "notty",
        "litter_box_action",
        {"user_device_id": "box-1", "action": "set_litter_reminder_days", "data": {"cycle_time": 29}},
        blocking=True,
    )
    runtime_api.litter_action.assert_awaited_once_with(
        "box-1", "set_litter_reminder_days", {"action": 3, "cycle_time": 29}
    )


@pytest.mark.parametrize("enabled", [False, None, 8])
async def test_generic_litter_interval_rejects_disabled(
    hass: HomeAssistant, runtime_api: MagicMock, enabled: object
) -> None:
    """Reject action 3 if the current reminder is not confirmed enabled."""
    runtime_api.device_info.return_value.update({"open_litter_remind": enabled, "default_remaining_days": 30})
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="enabled reminder"):
        await hass.services.async_call(
            "notty",
            "litter_box_action",
            {"user_device_id": "box-1", "action": "set_litter_reminder_days", "data": {"cycle_time": 29}},
            blocking=True,
        )
    runtime_api.litter_action.assert_not_awaited()


async def test_generic_litter_interval_rejects_unchanged(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Avoid running an unverified reset via an unchanged cycle value."""
    runtime_api.device_info.return_value.update({"open_litter_remind": True, "default_remaining_days": 30})
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="unchanged"):
        await hass.services.async_call(
            "notty",
            "litter_box_action",
            {"user_device_id": "box-1", "action": "set_litter_reminder_days", "data": {"cycle_time": 30}},
            blocking=True,
        )
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("reminder", REMINDERS)
async def test_generic_reset_service_requires_an_explicit_cycle(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder
) -> None:
    """An existing cycle does not justify sending unverified reset action codes."""
    action, _, cycle_key, _, cycle = reminder
    reset_action = "reset_litter_reminder" if action == ACTION_LITTER else "reset_garbage_bag_reminder"
    runtime_api.device_info.return_value[cycle_key] = cycle
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="cycle_time"):
        await hass.services.async_call(
            "notty", "litter_box_action", {"user_device_id": "box-1", "action": reset_action}, blocking=True
        )
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("reminder", REMINDERS)
async def test_generic_reset_service_rejects_missing_interval(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder
) -> None:
    """Do not turn the remaining-day counter into a guessed configured cycle."""
    action, _, _, _, _ = reminder
    reset_action = "reset_litter_reminder" if action == ACTION_LITTER else "reset_garbage_bag_reminder"
    runtime_api.device_info.return_value["remaining_days"] = 12
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="cycle_time"):
        await hass.services.async_call(
            "notty", "litter_box_action", {"user_device_id": "box-1", "action": reset_action}, blocking=True
        )
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("reminder", REMINDERS)
async def test_generic_interval_service_rejects_out_of_range_value(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder
) -> None:
    """Invalid interval writes are rejected at the HA service boundary."""
    action, _, _, _, _ = reminder
    set_action = "set_litter_reminder_days" if action == ACTION_LITTER else "set_garbage_bag_reminder_days"
    await setup(hass)
    with pytest.raises(HomeAssistantError, match=r"cycle_time|disabled pending live endpoint verification"):
        await hass.services.async_call(
            "notty",
            "litter_box_action",
            {"user_device_id": "box-1", "action": set_action, "data": {"cycle_time": 100}},
            blocking=True,
        )
    runtime_api.litter_action.assert_not_awaited()
