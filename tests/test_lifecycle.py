from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notty.api import NottyAuthError
from custom_components.notty.select import SELECTS

EXPECTED_2 = "2"
EXPECTED_OFF = "off"
EXPECTED_4_2 = "4.2"
EXPECTED_REAUTH = "reauth"
EXPECTED_NEW_CREDENTIAL = "new-token"
EXPECTED_UNAVAILABLE = "unavailable"
EXPECTED_START = "start"
EXPECTED_END = "end"
ACTION_SET_DND = "set_dnd"
EXPECTED_SWITCH = "switch"
EXPECTED_TIME = "time"
EXPECTED_101 = "101"
EXPECTED_9001 = "9001"
EXPECTED_BLOCK_INFO_PET_DEVICES_0_USER_DEVICE_ID = 9001
FIELD_MODE = "mode"
EXPECTED_AUTO = "Auto"
EXPECTED_5_MINUTES = "5 minutes"
EXPECTED_LEN_ENTITY_ATTRIBUTES_OPTIONS = 15
EXPECTED_5 = "5"
EXPECTED_UNKNOWN = "unknown"
EXPECTED_DND_START_UTC = "14:00:00"
EXPECTED_DND_END_UTC = "23:00:00"
EXPECTED_ENTITY_ATTRIBUTES_RAW_VALUE = 30
EXPECTED_30_MINUTES = "30 minutes"


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    """Setup.

    Returns:
        MockConfigEntry: The resulting setup.
    """
    entry = MockConfigEntry(
        domain="notty",
        version=2,
        unique_id="test@example.test",
        data={"email": "test@example.test", "access_token": "test-token", "user_id": "test-user"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_entities_services_and_unload(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify setup entities services and unload."""
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    runtime_api.login.assert_not_awaited()
    assert hass.states.get("sensor.test_box_today_clean_count").state == EXPECTED_2
    assert hass.states.get("switch.test_box_child_lock").state == EXPECTED_OFF
    assert hass.states.get("number.test_cat_weight").state == EXPECTED_4_2
    assert not any(s.entity_id.startswith("button.test_cat_") for s in hass.states.async_all())
    registry = async_get_device_registry(hass)
    parent = registry.async_get_device_by_identifier(("notty", "box-1"), entry.entry_id)
    pet = registry.async_get_device_by_identifier(("notty", "pet_cat-1"), entry.entry_id)
    assert parent is not None
    assert pet is not None
    assert pet.via_device_id == parent.id
    await hass.services.async_call(
        "notty", "litter_box_one_key", {"user_device_id": "box-1", "one_key": "clean"}, blocking=True
    )
    runtime_api.command.assert_awaited_once_with("box-1", 0, "litter_box")
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("notty", "litter_box_action")


async def test_expired_token_requests_reauthentication(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify expired token requests reauthentication."""
    runtime_api.devices.side_effect = NottyAuthError("expired")
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    runtime_api.login.assert_not_awaited()
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == EXPECTED_REAUTH for flow in flows)


async def test_reauthenticated_token_is_persisted(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify reauthenticated token is persisted."""
    entry = await setup(hass)
    runtime_api.token = RENEWED_SESSION
    await entry.runtime_data.async_refresh()
    assert entry.data["access_token"] == EXPECTED_NEW_CREDENTIAL


async def test_disappearing_device_becomes_unavailable(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify disappearing device becomes unavailable."""
    entry = await setup(hass)
    runtime_api.devices.return_value = []
    await entry.runtime_data.async_refresh()
    assert hass.states.get("sensor.test_box_today_clean_count").state == EXPECTED_UNAVAILABLE


async def test_unknown_device_rejected_before_command(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify unknown device rejected before command."""
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="not found"):
        await hass.services.async_call(
            "notty", "litter_box_one_key", {"user_device_id": "unknown", "one_key": "clean"}, blocking=True
        )
    runtime_api.command.assert_not_called()


async def test_pet_id_rejected_before_hardware_command(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify pet id rejected before hardware command."""
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="physical litter box"):
        await hass.services.async_call(
            "notty", "litter_box_one_key", {"user_device_id": "pet_cat-1", "one_key": "clean"}, blocking=True
        )
    runtime_api.command.assert_not_called()


@pytest.mark.parametrize("boundary", ["start", "end"])
async def test_dnd_time_preserves_other_settings(hass: HomeAssistant, runtime_api: MagicMock, boundary: str) -> None:
    """Verify dnd time preserves other settings."""
    hass.config.time_zone = "Asia/Shanghai"
    await setup(hass)
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": f"time.test_box_do_not_disturb_{boundary}", "time": "21:30:00"},
        blocking=True,
    )
    runtime_api.litter_action.assert_awaited_once_with(
        "box-1",
        "set_dnd",
        {
            "switch": 1,
            "led": 2,
            "dnd_begin_time": "21:30" if boundary == EXPECTED_START else "22:00",
            "dnd_end_time": "21:30" if boundary == EXPECTED_END else "07:00",
        },
    )


@pytest.mark.parametrize(("service", "expected"), [("turn_on", 1), ("turn_off", 0)])
@pytest.mark.parametrize("setting_action", [("child_lock", "set_key"), ("do_not_disturb", "set_dnd")])
async def test_switch_uses_write_field_and_preserves_dnd(
    hass: HomeAssistant, runtime_api: MagicMock, service: str, expected: object, setting_action: tuple[str, str]
) -> None:
    """Verify switch uses write field and preserves dnd."""
    setting, action = setting_action
    hass.config.time_zone = "Asia/Shanghai"
    await setup(hass)
    await hass.services.async_call("switch", service, {"entity_id": f"switch.test_box_{setting}"}, blocking=True)
    payload = {"switch": expected}
    if action == ACTION_SET_DND:
        payload.update(led=2, dnd_begin_time="22:00", dnd_end_time="07:00")
    runtime_api.litter_action.assert_awaited_once_with("box-1", action, payload)


@pytest.mark.parametrize("missing", ["led", "dnd_end_time"])
@pytest.mark.parametrize("platform", ["switch", "time"])
async def test_missing_shared_dnd_setting_prevents_write(
    hass: HomeAssistant, runtime_api: MagicMock, missing: str, platform: str
) -> None:
    """Verify missing shared dnd setting prevents write."""
    runtime_api.device_info.return_value.pop(missing)
    hass.config.time_zone = "Asia/Shanghai"
    await setup(hass)
    service = "turn_off" if platform == EXPECTED_SWITCH else "set_value"
    entity = "switch.test_box_do_not_disturb" if platform == EXPECTED_SWITCH else "time.test_box_do_not_disturb_start"
    data = {"entity_id": entity}
    if platform == EXPECTED_TIME:
        data["time"] = "21:30:00"
    with pytest.raises(HomeAssistantError, match="Cannot preserve"):
        await hass.services.async_call(platform, service, data, blocking=True)
    runtime_api.litter_action.assert_not_awaited()


async def test_dnd_ha_time_entity_converts_readback(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """HA displays the Shanghai-coded API time in the configured local timezone."""
    hass.config.time_zone = "UTC"
    runtime_api.device_info.return_value.update({
        "time_zone_iana": "Asia/Shanghai",
        "dnd_begin_time": "22:00",
        "dnd_end_time": "07:00",
    })
    await setup(hass)
    start = hass.states.get("time.test_box_do_not_disturb_start")
    end = hass.states.get("time.test_box_do_not_disturb_end")
    assert start is not None
    assert end is not None
    assert start.state == EXPECTED_DND_START_UTC
    assert end.state == EXPECTED_DND_END_UTC
    await hass.services.async_call(
        "time", "set_value", {"entity_id": "time.test_box_do_not_disturb_start", "time": "15:30:00"}, blocking=True
    )
    runtime_api.litter_action.assert_awaited_once_with(
        "box-1", "set_dnd", {"switch": 1, "led": 2, "dnd_begin_time": "23:30", "dnd_end_time": "07:00"}
    )


async def test_live_shape_pet_binding_survives_merge(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify live shape pet binding survives merge."""
    runtime_api.devices.return_value = [
        {
            "user_device_id": 9001,
            "device_name": "Cat Automatic Litter Box",
            "_notty_source": "device",
            "_notty_pet_ids": ["101", "102"],
        },
        *[
            {
                "id": f"pet_{pet_id}",
                "pet_id": pet_id,
                "name": name,
                "alias": name,
                "device_type": "litter_box",
                "bind_litter_box": True,
                "_notty_source": "pet",
                "_notty_litter_user_device_id": None,
            }
            for pet_id, name in ((101, "Alpha"), (102, "Beta"))
        ],
    ]
    runtime_api.litter_related_info.return_value = {
        "associated_pets": [
            {"pet_id": 101, "name": "Alpha", "is_associated": True},
            {"pet_id": 102, "name": "Beta", "is_associated": True},
        ]
    }
    runtime_api.pet_related_info.side_effect = lambda pet_id: {
        "info": {
            "pet_id": int(pet_id),
            "name": "Alpha" if pet_id == EXPECTED_101 else "Beta",
            "weight": 4.2,
            "pet_devices": [{"is_bind": True, "user_device_id": 9001, "device_id": 2}],
        }
    }
    entry = await setup(hass)
    for pet_id in (101, 102):
        block = entry.runtime_data.data[f"pet_{pet_id}"]
        assert block["device"]["_notty_litter_user_device_id"] == EXPECTED_9001
        assert block["info"]["litter_user_device_id"] == EXPECTED_9001
        assert block["info"]["pet_devices"][0]["user_device_id"] == EXPECTED_BLOCK_INFO_PET_DEVICES_0_USER_DEVICE_ID


async def test_mode_1_is_auto_and_mode_changes_are_blocked(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Raw mode=1 was verified as Auto in the actual NOTTY mobile app."""
    modes = next(description for description in SELECTS if description.key == FIELD_MODE)
    assert modes.value_options == {1: "Auto"}

    await setup(hass)
    mode = hass.states.get("select.test_box_mode")
    assert mode is not None
    assert mode.state == EXPECTED_AUTO
    assert mode.attributes["options"] == ["Auto"]
    with pytest.raises(HomeAssistantError, match="disabled until remaining mode codes"):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": "select.test_box_mode", "option": "Auto"}, blocking=True
        )
    runtime_api.litter_action.assert_not_awaited()


@pytest.mark.parametrize("delay", [1, 15])
async def test_cleaning_delay_options_and_write(hass: HomeAssistant, runtime_api: MagicMock, delay: object) -> None:
    """Verify cleaning delay options and write."""
    runtime_api.device_info.return_value["auto_delay"] = "5"
    await setup(hass)
    entity = hass.states.get("select.test_box_automatic_cleaning_delay")
    assert entity.state == EXPECTED_5_MINUTES
    assert len(entity.attributes["options"]) == EXPECTED_LEN_ENTITY_ATTRIBUTES_OPTIONS
    assert entity.attributes["raw_value"] == EXPECTED_5
    runtime_api.device_info.reset_mock()
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity.entity_id, "option": f"{delay} minute" + ("s" if delay != 1 else "")},
        blocking=True,
    )
    runtime_api.litter_action.assert_awaited_once_with("box-1", "set_auto_delay", {"delay": delay})
    runtime_api.device_info.assert_awaited()


@pytest.mark.parametrize("mode", [2, 3, None])
async def test_cleaning_delay_unavailable_outside_auto_mode(
    hass: HomeAssistant, runtime_api: MagicMock, mode: int | None
) -> None:
    """Verify cleaning delay unavailable outside auto mode."""
    runtime_api.device_info.return_value.update(auto_delay=5, mode=mode)
    await setup(hass)
    entity = hass.states.get("select.test_box_automatic_cleaning_delay")
    assert entity.state == EXPECTED_UNAVAILABLE
    # HA skips unavailable entities before invoking their service method.
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity.entity_id, "option": "1 minute"}, blocking=True
    )
    runtime_api.litter_action.assert_not_awaited()


async def test_unknown_cleaning_delay_is_not_offered_as_an_option(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Verify unknown cleaning delay is not offered as an option."""
    runtime_api.device_info.return_value["auto_delay"] = 30
    await setup(hass)
    entity = hass.states.get("select.test_box_automatic_cleaning_delay")
    assert entity.state == EXPECTED_UNKNOWN
    assert entity.attributes["raw_value"] == EXPECTED_ENTITY_ATTRIBUTES_RAW_VALUE
    assert EXPECTED_30_MINUTES not in entity.attributes["options"]


@pytest.mark.usefixtures("runtime_api")
async def test_missing_cleaning_delay_does_not_create_entity(hass: HomeAssistant) -> None:
    """Verify missing cleaning delay does not create entity."""
    await setup(hass)
    assert hass.states.get("select.test_box_automatic_cleaning_delay") is None


RENEWED_SESSION = "new-token"
