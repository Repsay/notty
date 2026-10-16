import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notty.api import NottyAuthError


async def setup(hass):
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


async def test_setup_entities_services_and_unload(hass, runtime_api):
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.test_box_today_clean_count").state == "2"
    assert hass.states.get("switch.test_box_child_lock").state == "off"
    assert hass.states.get("number.test_cat_weight").state == "4.2"
    assert not any(s.entity_id.startswith("button.test_cat_") for s in hass.states.async_all())
    await hass.services.async_call(
        "notty",
        "litter_box_one_key",
        {"user_device_id": "box-1", "one_key": "clean"},
        blocking=True,
    )
    runtime_api.command.assert_awaited_once_with("box-1", 0, "litter_box")
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("notty", "litter_box_action")


async def test_expired_token_requests_reauthentication(hass, runtime_api):
    runtime_api.devices.side_effect = NottyAuthError("expired")
    entry = await setup(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_reauthenticated_token_is_persisted(hass, runtime_api):
    entry = await setup(hass)
    runtime_api.token = "new-token"
    await entry.runtime_data.async_refresh()
    assert entry.data["access_token"] == "new-token"


async def test_disappearing_device_becomes_unavailable(hass, runtime_api):
    entry = await setup(hass)
    runtime_api.devices.return_value = []
    await entry.runtime_data.async_refresh()
    assert hass.states.get("sensor.test_box_today_clean_count").state == "unavailable"


async def test_unknown_device_rejected_before_command(hass, runtime_api):
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="not found"):
        await hass.services.async_call(
            "notty",
            "litter_box_one_key",
            {"user_device_id": "unknown", "one_key": "clean"},
            blocking=True,
        )
    runtime_api.command.assert_not_called()


async def test_pet_id_rejected_before_hardware_command(hass, runtime_api):
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="physical litter box"):
        await hass.services.async_call(
            "notty",
            "litter_box_one_key",
            {"user_device_id": "pet_cat-1", "one_key": "clean"},
            blocking=True,
        )
    runtime_api.command.assert_not_called()


async def test_dnd_time_preserves_other_settings(hass, runtime_api):
    await setup(hass)
    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.test_box_do_not_disturb_start", "time": "21:30:00"},
        blocking=True,
    )
    runtime_api.litter_action.assert_awaited_once_with(
        "box-1", "set_dnd", {"switch_dnd": 1, "dnd_begin_time": "21:30", "dnd_end_time": "07:00"}
    )


async def test_live_shape_pet_binding_survives_merge(hass, runtime_api):
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
            "name": "Alpha" if pet_id == "101" else "Beta",
            "weight": 4.2,
            "pet_devices": [{"is_bind": True, "user_device_id": 9001, "device_id": 2}],
        }
    }
    entry = await setup(hass)
    for pet_id in (101, 102):
        block = entry.runtime_data.data[f"pet_{pet_id}"]
        assert block["device"]["_notty_litter_user_device_id"] == "9001"
        assert block["info"]["litter_user_device_id"] == "9001"
        assert block["info"]["pet_devices"][0]["user_device_id"] == 9001
