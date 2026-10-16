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
DISABLE = 3
REMINDERS = [
    Reminder(ACTION_LITTER, "open_litter_remind", "default_remaining_days", "litter_renewal_reminder", 20),
    Reminder("set_garbage_bag_remind", "open_garbagebag_remind", "garbage_bag_cycle_time", "trash_bag_reminder", 7),
]
EXPECTED_UNKNOWN = "unknown"
EXPECTED_OFF = "off"
EXPECTED_ON = "on"


@pytest.mark.parametrize("reminder", REMINDERS)
@pytest.mark.parametrize("operation", [1, 2, 3])
async def test_wire_contract(reminder: Reminder, operation: int) -> None:
    """Match the app's action and cycle fields without leaking read-state fields."""
    action, _, _, _, cycle = reminder
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    data = {"action": operation, "cycle_time": cycle, "open_litter_remind": 1, "remaining_days": 1}
    before = data.copy()
    await api.litter_action("box-1", action, data)
    expected = {"action": operation, "user_device_id": "box-1", "device_id": "box-1"}
    if operation != DISABLE:
        expected["cycle_time"] = cycle
    endpoint = (
        "/device/litter_box/set_litter_remind"
        if action == ACTION_LITTER
        else "/device/litter_box/set_garbage_bag_remind"
    )
    api.request.assert_awaited_once_with("POST", endpoint, data=expected)
    assert data == before


@pytest.mark.parametrize(
    "action",
    [
        "reset_litter_reminder",
        "set_litter_reminder_days",
        "reset_garbage_bag_reminder",
        "set_garbage_bag_reminder_days",
    ],
)
async def test_existing_service_operations_use_reset_code(action: str) -> None:
    """Reset and cycle adjustment use action 2, never the enable or disable code."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    await api.litter_action("box-1", action, {"cycle_time": 10, "action": 3})
    assert api.request.call_args.kwargs["data"] == {
        "action": 2,
        "cycle_time": 10,
        "user_device_id": "box-1",
        "device_id": "box-1",
    }


@pytest.mark.parametrize("cycle", [None, True, False, 1, 31, 3.5, "unknown", {}, []])
async def test_invalid_interval_never_writes(cycle: object) -> None:
    """Refuse guessed defaults or remaining-day counters as interval replacements."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="cycle_time"):
        await api.litter_action("box-1", "set_litter_remind", {"action": 1, "cycle_time": cycle})
    api.request.assert_not_awaited()


@pytest.mark.parametrize("operation", [None, True, False, 0, 4, "1", {}, []])
def test_invalid_operation_is_rejected(operation: object) -> None:
    """Do not confuse booleans or the read state with action enums."""
    with pytest.raises(NottyApiError, match="Reminder action"):
        reminder_payload("set_litter_remind", {"action": operation, "cycle_time": 20})


@pytest.mark.parametrize(
    ("action", "minimum", "maximum"), [("set_litter_remind", 5, 30), ("set_garbage_bag_remind", 2, 15)]
)
def test_interval_boundaries(action: str, minimum: int, maximum: int) -> None:
    """Use the picker ranges for each separate reminder."""
    for days in (minimum, maximum):
        assert reminder_payload(action, {"action": 1, "cycle_time": str(days)}) == {"action": 1, "cycle_time": days}
    for days in (minimum - 1, maximum + 1):
        with pytest.raises(NottyApiError, match="cycle_time"):
            reminder_payload(action, {"action": 1, "cycle_time": days})


@pytest.mark.parametrize("reminder", REMINDERS)
@pytest.mark.parametrize("transition", [("turn_on", 0, 1), ("turn_off", 1, 3)])
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
    expected = {"action": operation}
    if operation == 1:
        expected["cycle_time"] = cycle
    await hass.services.async_call("switch", service, {"entity_id": entity_id}, blocking=True)
    runtime_api.litter_action.assert_awaited_once_with("box-1", action, expected)
    assert runtime_api.device_info.return_value == before
    assert entry.runtime_data.last_update_success


@pytest.mark.parametrize("reminder", REMINDERS)
async def test_repeated_enable_does_not_restart_reminder(
    hass: HomeAssistant, runtime_api: MagicMock, reminder: Reminder
) -> None:
    """An already enabled switch must not reset the countdown."""
    _, field, cycle_key, entity, cycle = reminder
    runtime_api.device_info.return_value.update({field: 1, cycle_key: cycle})
    await setup(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": f"switch.test_box_{entity}"}, blocking=True)
    runtime_api.litter_action.assert_not_awaited()


async def test_enabling_requires_configured_interval(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A remaining-day measurement is never substituted for a missing interval."""
    runtime_api.device_info.return_value.update(open_litter_remind=0, remaining_days=12)
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="cycle_time"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.test_box_litter_renewal_reminder"}, blocking=True
        )
    runtime_api.litter_action.assert_not_awaited()


async def test_disabling_does_not_need_or_write_interval(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """The app's disable request contains no cycle field."""
    runtime_api.device_info.return_value.update(open_litter_remind=1)
    await setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.test_box_litter_renewal_reminder"}, blocking=True
    )
    runtime_api.litter_action.assert_awaited_once_with("box-1", "set_litter_remind", {"action": 3})


async def test_unknown_state_cannot_be_written(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Missing or novel enable enums are not silently treated as off."""
    runtime_api.device_info.return_value.update(open_litter_remind=8, default_remaining_days=20)
    await setup(hass)
    assert hass.states.get("switch.test_box_litter_renewal_reminder").state == EXPECTED_UNKNOWN
    with pytest.raises(HomeAssistantError, match="unknown current state"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.test_box_litter_renewal_reminder"}, blocking=True
        )
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize(
    ("button", "cycle_key", "cycle"),
    [
        ("reset_litter_reminder", "default_remaining_days", 20),
        ("reset_garbage_bag_reminder", "garbage_bag_cycle_time", 7),
    ],
)
async def test_reset_button_uses_configured_interval(
    hass: HomeAssistant, runtime_api: MagicMock, button: str, cycle_key: str, cycle: int
) -> None:
    """Existing reset buttons now send the complete app reset request."""
    runtime_api.device_info.return_value[cycle_key] = cycle
    await setup(hass)
    entity_name = "reset_litter_renewal_reminder" if button == RESET_LITTER else "reset_trash_bag_reminder"
    await hass.services.async_call("button", "press", {"entity_id": f"button.test_box_{entity_name}"}, blocking=True)
    runtime_api.litter_action.assert_awaited_once_with("box-1", button, {"action": 2, "cycle_time": cycle})
    runtime_api.endpoint_action.assert_not_awaited()


@pytest.mark.usefixtures("runtime_api")
async def test_unsupported_device_has_no_reminder_switch(hass: HomeAssistant) -> None:
    """Do not create controls for fields the device does not report."""
    await setup(hass)
    assert hass.states.get("switch.test_box_litter_renewal_reminder") is None
    assert hass.states.get("switch.test_box_trash_bag_reminder") is None
