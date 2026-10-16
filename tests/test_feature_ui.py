"""Native HA controls, action schemas, ownership and account-preference lifecycle."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from unittest.mock import MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import async_get as devices
from homeassistant.helpers.entity_registry import async_get as entities
import pytest
import yaml

from custom_components.notty.api import JsonObject, JsonValue
from custom_components.notty.feature_services import FEATURE_SERVICES
from tests.test_device_features import CATEGORIES, UPGRADE
from tests.test_lifecycle import setup
from tests.test_pet_features import BOX_ID, NEW_NAME, PET_ID, PROFILE

METHOD_GET = "GET"
METHOD_POST = "POST"
EXPECTED_ON = "on"
EXPECTED_OFF = "off"
EXPECTED_UNAVAILABLE = "unavailable"
HA_OVERRIDE = "My cat display name"
SERVICE_PROFILE = "pet_profile"
SERVICE_MEMO = "pet_memo"
DOMAIN = "notty"
MALE = "male"
FEMALE_CODE = 2
NEW_BIRTHDAY = "2021-04-03"
PET_SAVE = "/pet/save"
CLEANING = "cleaning"
FIELD_IMAGE_URL = "image_url"


def configure(runtime_api: MagicMock) -> tuple[JsonObject, list[JsonValue]]:
    """Set up a writable fake cloud with independent authoritative readback.

    Returns:
        Mutable server pet data and account category data for explicit polling tests.
    """
    profile = deepcopy(PROFILE)
    categories = deepcopy(CATEGORIES)
    runtime_api.devices.return_value = [
        {"user_device_id": 123, "device_type": "litter_box", "alias": "Test box", "is_owner": True, "status_id": 1},
        {**profile, "_notty_source": "pet", "device_type": "litter_box", "id": "pet_7", "alias": "Milo"},
    ]
    runtime_api.pets.return_value = [{"pet_id": 7}]
    runtime_api.device_info.return_value.update({"user_device_id": 123, "mode": 1, "language": 1})
    runtime_api.pet_related_info.return_value = {"info": profile, "memos": []}

    def request(method: str, path: str, *, data: JsonObject | None = None) -> JsonValue:
        if path.startswith("/message/get_type_block_stats_list"):
            return deepcopy(categories)
        if path.startswith("/pet/info/"):
            return deepcopy(profile)
        if method == METHOD_POST and path.endswith("/pet/save"):
            assert data is not None
            profile.update(data)
            return {}
        if path.endswith("/message/block_type"):
            assert data is not None
            for row in categories:
                if row["message_type_id"] == data["message_type_id"]:
                    row["blocked"] = data["block"]
            return {}
        return [] if path.startswith("/pet/memos/") else UPGRADE if path.endswith("/device/check_upgrade/123") else {}

    runtime_api.request.side_effect = request
    return profile, categories


async def test_native_pet_controls_keep_names_and_entity_identity(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Editing a cloud pet updates readback without losing the HA display-name override."""
    configure(runtime_api)
    entry = await setup(hass)
    registry = devices(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        pet = registry.async_get_device_by_identifier((DOMAIN, "pet_7"), entry.entry_id)
    else:
        pet = registry.async_get_device(identifiers={(DOMAIN, "pet_7")})
    assert pet is not None
    registry.async_update_device(pet.id, name_by_user=HA_OVERRIDE)
    before = {(item.entity_id, item.unique_id, item.device_id) for item in entities(hass).entities.values()}
    assert hass.states.get("text.milo_name").state == PROFILE["name"]
    assert hass.states.get("select.milo_sex").state == MALE
    assert hass.states.get("date.milo_birthday").state == PROFILE["birthday"]
    await hass.services.async_call(
        "text", "set_value", {"entity_id": "text.milo_name", "value": NEW_NAME}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("text.milo_name").state == NEW_NAME
    assert registry.async_get(pet.id).name == NEW_NAME
    assert registry.async_get(pet.id).name_by_user == HA_OVERRIDE
    assert {(item.entity_id, item.unique_id, item.device_id) for item in entities(hass).entities.values()} == before


async def test_pet_profile_sex_neutered_and_birthday_controls(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Native setters write through the full profile-preserving path."""
    profile, _ = configure(runtime_api)
    await setup(hass)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.milo_sex", "option": "female"}, blocking=True
    )
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.milo_neutered"}, blocking=True)
    await hass.services.async_call(
        "date", "set_value", {"entity_id": "date.milo_birthday", "date": date(2021, 4, 3)}, blocking=True
    )
    assert profile["sex"] == FEMALE_CODE
    assert profile["is_sterilization"] is True
    assert profile["birthday"] == NEW_BIRTHDAY
    posts = [call for call in runtime_api.request.await_args_list if call.args[0] == METHOD_POST]
    assert all(call.args[1] == PET_SAVE and call.kwargs["data"]["user_device_ids"] == BOX_ID for call in posts)


async def test_shared_pet_controls_are_unavailable_and_cannot_write(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """Permission changes are visible in the native UI, not only in error handling."""
    profile, _ = configure(runtime_api)
    profile["is_owner"] = False
    await setup(hass)
    for entity_id in ("text.milo_name", "select.milo_sex", "switch.milo_neutered", "date.milo_birthday"):
        assert hass.states.get(entity_id).state == EXPECTED_UNAVAILABLE
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "notty",
            SERVICE_PROFILE,
            {"pet_id": PET_ID, "operation": "update", "changes": {"name": NEW_NAME}},
            blocking=True,
        )
    assert all(call.args[0] == METHOD_GET for call in runtime_api.request.await_args_list)


async def test_notification_only_poll_changes_update_the_ui(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Coordinator equality must notice account preference changes independently of measurements."""
    _, categories = configure(runtime_api)
    entry = await setup(hass)
    switches = [state for state in hass.states.async_all("switch") if CLEANING in state.entity_id]
    assert len(switches) == 1
    entity_id = switches[0].entity_id
    assert hass.states.get(entity_id).state == EXPECTED_ON
    categories[0]["blocked"] = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == EXPECTED_OFF
    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    assert hass.states.get(entity_id).state == EXPECTED_ON
    posts = [call for call in runtime_api.request.await_args_list if call.args[0] == METHOD_POST]
    assert posts[-1].kwargs["data"] == {"message_type_id": 12, "block": False}


@pytest.mark.parametrize(
    ("service", "data"),
    [
        (SERVICE_PROFILE, {"pet_id": 7, "operation": "get", "changes": {"name": NEW_NAME}}),
        (SERVICE_PROFILE, {"pet_id": 999, "operation": "update", "changes": {"name": NEW_NAME}}),
        (SERVICE_MEMO, {"pet_id": 7, "operation": "create", "memo_id": 42, "changes": {}}),
        (SERVICE_MEMO, {"pet_id": 7, "operation": "update", "changes": {}}),
        ("notification_preferences", {"user_device_id": 123, "operation": "list", "message_type_id": 12}),
        ("clear_statistics", {"user_device_id": 123, "confirm_irreversible": False}),
    ],
)
async def test_actions_reject_mismatched_fields_and_unknown_targets_before_writing(
    hass: HomeAssistant, runtime_api: MagicMock, service: str, data: JsonObject
) -> None:
    """A read operation cannot silently accept write inputs or target another account."""
    configure(runtime_api)
    await setup(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("notty", service, data, blocking=True)
    assert all(call.args[0] == METHOD_GET for call in runtime_api.request.await_args_list)


async def test_feature_services_unload_with_last_account(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Every new action follows the existing integration lifecycle."""
    configure(runtime_api)
    entry = await setup(hass)
    assert all(hass.services.has_service("notty", service) for service in FEATURE_SERVICES)
    await hass.config_entries.async_unload(entry.entry_id)
    assert all(not hass.services.has_service("notty", service) for service in FEATURE_SERVICES)


async def test_firmware_install_tracks_offered_target_until_version_readback(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """An acknowledged request never fabricates installed version or percentage progress."""
    configure(runtime_api)
    runtime_api.litter_related_info.return_value["upgrade"] = dict(UPGRADE)
    entry = await setup(hass)
    entity = "update.test_box_firmware"
    state = hass.states.get(entity)
    assert state.attributes["supported_features"] & UpdateEntityFeature.INSTALL
    await hass.services.async_call("update", "install", {"entity_id": entity}, blocking=True)
    state = hass.states.get(entity)
    assert state.attributes["in_progress"] is True
    assert state.attributes["installed_version"] == UPGRADE["src_version"]
    assert state.attributes.get("update_percentage") is None
    runtime_api.litter_related_info.return_value["upgrade"] = {
        **UPGRADE,
        "src_version": UPGRADE["dest_version"],
        "dest_version": "",
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity).attributes["in_progress"] is False


def test_ui_metadata_covers_all_new_entities_and_services() -> None:
    """Icons, English/Dutch names and action fields remain aligned with registration."""
    root = Path(__file__).resolve().parents[1] / "custom_components" / "notty"
    icons = json.loads((root / "icons.json").read_text())
    schema = yaml.safe_load((root / "services.yaml").read_text())
    for language in ("en", "nl"):
        translations = json.loads((root / "translations" / f"{language}.json").read_text())
        for service in FEATURE_SERVICES:
            assert icons["services"][service]["service"].startswith("mdi:")
            assert set(translations["services"][service]["fields"]) == set(schema[service]["fields"])
        for platform, key in (
            ("text", "pet_name"),
            ("date", "pet_birthday"),
            ("select", "pet_sex"),
            ("switch", "pet_neutered"),
            ("switch", "notification_category"),
        ):
            assert translations["entity"][platform][key]["name"]
            assert icons["entity"][platform][key]["default"].startswith("mdi:")


async def test_notification_endpoint_loss_and_late_recovery(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Optional failures keep measurements running and recovered categories appear once."""
    _, categories = configure(runtime_api)
    saved = deepcopy(categories)
    categories.clear()
    entry = await setup(hass)
    assert not any(CLEANING in state.entity_id for state in hass.states.async_all("switch"))
    categories.extend(saved)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    switches = [state for state in hass.states.async_all("switch") if CLEANING in state.entity_id]
    assert len(switches) == 1
    entity_id = switches[0].entity_id
    categories[0]["blocked"] = None
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == EXPECTED_UNAVAILABLE
    assert hass.states.get("sensor.test_box_today_clean_count").state != EXPECTED_UNAVAILABLE
    categories[0]["blocked"] = False
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == EXPECTED_ON
    assert len([state for state in hass.states.async_all("switch") if CLEANING in state.entity_id]) == 1


async def test_profile_action_returns_filtered_authoritative_readback(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """Native actions return fresh profile values without unrelated backend fields."""
    profile, _ = configure(runtime_api)
    profile["image_url"] = "https://example.invalid/private-image"
    await setup(hass)
    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PROFILE,
        {"pet_id": PET_ID, "operation": "update", "changes": {"name": NEW_NAME}},
        blocking=True,
        return_response=True,
    )
    assert result["profile"]["name"] == NEW_NAME
    assert FIELD_IMAGE_URL not in result["profile"]
    post = next(call for call in runtime_api.request.await_args_list if call.args[0] == METHOD_POST)
    assert post.kwargs["data"]["image_url"] == profile["image_url"]


async def test_statistics_action_requires_explicit_confirmation_and_exact_target(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """The destructive service uses its scoped empty-body APK contract once."""
    configure(runtime_api)
    await setup(hass)
    result = await hass.services.async_call(
        DOMAIN,
        "clear_statistics",
        {"user_device_id": BOX_ID, "confirm_irreversible": True},
        blocking=True,
        return_response=True,
    )
    assert result["reversible"] is False
    posts = [call for call in runtime_api.request.await_args_list if call.args[0] == METHOD_POST]
    assert len(posts) == 1
    assert posts[0].args == (METHOD_POST, "/device/clear_statistics/123")
    assert posts[0].kwargs["data"] == {}
