"""Cloud alias contracts and identity preservation with synthetic device names."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import async_get as async_get_device_registry
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
import pytest

from custom_components.notty.api import NottyApi, NottyApiError, alias_payload
from tests.test_lifecycle import setup

CONTRACT = json.loads((Path(__file__).parent / "fixtures/apk_cloud_alias.json").read_text())
ENTITY = "text.test_box_cloud_name"
EXPECTED_ALIAS = "Cat Box"
EXPECTED_ORIGINAL = "Test box"
EXPECTED_OVERRIDE = "My own HA name"
EXPECTED_UNIQUE_ID = "123_cloud_alias"
EXPECTED_UNAVAILABLE = "unavailable"
EXPECTED_LEGACY_NAME = "A longer legacy cloud name"


async def test_alias_wire_contract() -> None:
    """Use the app's integer ID and exact two-field request without a device_id alias."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    await api.set_device_alias("123", "Cat Box")
    api.request.assert_awaited_once_with("POST", CONTRACT["endpoint"], data=CONTRACT["payload"])
    api.request.reset_mock()
    await api.litter_action("123", "set_alias", {"alias": "Cat Box"})
    api.request.assert_awaited_once_with("POST", CONTRACT["endpoint"], data=CONTRACT["payload"])


@pytest.mark.parametrize("value", ["AB", "12345678", "Cat Box", " A ", "\U0001f63a", "\U0001f63a" * 4, "猫砂盆"])
def test_alias_uses_dart_length_and_preserves_text(value: str) -> None:
    """Non-BMP characters consume two UTF-16 units and spaces are not silently trimmed."""
    assert alias_payload("123", value) == {"user_device_id": 123, "alias": value}


@pytest.mark.parametrize(
    "value", [None, True, 123, {}, [], "", "A", "123456789", " " * 3, "A\nB", "A\tB", "\ud800\udfff", "\U0001f63a" * 5]
)
async def test_invalid_alias_never_reaches_cloud(value: object) -> None:
    """Apply conservative app guidance without truncation or permissive type coercion."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError):
        await api.set_device_alias("123", value)
    api.request.assert_not_awaited()


@pytest.mark.parametrize("device_id", ["", "0", "-1", "pet_123", "box-1", "12/3", " 123", "\uff11\uff12\uff13"])
async def test_invalid_physical_ids_never_reach_cloud(device_id: str) -> None:
    """Do not convert a pet ID, synthetic identifier or malformed input into a target."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="physical user_device_id"):
        await api.set_device_alias(device_id, "Cat Box")
    api.request.assert_not_awaited()


async def test_generic_alias_action_rejects_target_overrides() -> None:
    """The selected physical ID cannot be replaced by payload aliases or extra keys."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="only the alias"):
        await api.litter_action("123", "set_alias", {"alias": "Cat Box", "user_device_id": "other"})
    api.request.assert_not_awaited()


def numeric_device(runtime_api: MagicMock) -> None:
    """Use a synthetic integer-shaped physical ID as required by the app."""
    runtime_api.devices.return_value[0]["user_device_id"] = "123"


async def test_cloud_rename_preserves_registry_identity_and_user_override(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """A confirmed cloud readback changes integration naming without changing HA identity."""
    numeric_device(runtime_api)
    entry = await setup(hass)
    registry = async_get_device_registry(hass)
    device = (
        registry.async_get_device_by_identifier(("notty", "123"), entry.entry_id)
        if hasattr(registry, "async_get_device_by_identifier")
        else registry.async_get_device(identifiers={("notty", "123")})
    )
    registry.async_update_device(device.id, name_by_user=EXPECTED_OVERRIDE)
    entities = async_get_entity_registry(hass)
    registered = entities.async_get(ENTITY)
    assert registered.unique_id == EXPECTED_UNIQUE_ID
    assert registered.entity_category is EntityCategory.CONFIG
    before_ids = set(entities.entities)
    before_identifiers = device.identifiers

    def accept() -> None:
        """Simulate an authoritative alias returned by subsequent cloud discovery."""
        runtime_api.devices.return_value[0]["alias"] = EXPECTED_ALIAS

    runtime_api.set_device_alias.side_effect = lambda *_: accept()
    await hass.services.async_call("text", "set_value", {"entity_id": ENTITY, "value": EXPECTED_ALIAS}, blocking=True)
    await hass.async_block_till_done()
    runtime_api.set_device_alias.assert_awaited_once_with("123", EXPECTED_ALIAS)
    assert hass.states.get(ENTITY).state == EXPECTED_ALIAS
    updated = registry.async_get(device.id)
    assert updated.id == device.id
    assert updated.identifiers == before_identifiers
    assert updated.name == EXPECTED_ALIAS
    assert updated.name_by_user == EXPECTED_OVERRIDE
    assert set(entities.entities) == before_ids
    assert entities.async_get(ENTITY).unique_id == EXPECTED_UNIQUE_ID


async def test_unconfirmed_response_does_not_optimistically_rename(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """An accepted request alone cannot overwrite the last reported cloud name."""
    numeric_device(runtime_api)
    await setup(hass)
    await hass.services.async_call("text", "set_value", {"entity_id": ENTITY, "value": EXPECTED_ALIAS}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_ORIGINAL


async def test_cloud_rename_error_keeps_name_and_does_not_retry(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A cloud error leaves registry/state intact and is surfaced once."""
    numeric_device(runtime_api)
    await setup(hass)
    runtime_api.set_device_alias.side_effect = NottyApiError("rejected")
    with pytest.raises(HomeAssistantError, match="rejected"):
        await hass.services.async_call(
            "text", "set_value", {"entity_id": ENTITY, "value": EXPECTED_ALIAS}, blocking=True
        )
    runtime_api.set_device_alias.assert_awaited_once()
    assert hass.states.get(ENTITY).state == EXPECTED_ORIGINAL


async def test_repeated_alias_is_a_noop(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Writing the already reported name never submits a redundant request."""
    numeric_device(runtime_api)
    await setup(hass)
    await hass.services.async_call(
        "text", "set_value", {"entity_id": ENTITY, "value": EXPECTED_ORIGINAL}, blocking=True
    )
    runtime_api.set_device_alias.assert_not_awaited()


async def test_utf16_limit_is_checked_at_ha_boundary(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Five emoji fit HA's codepoint limit but exceed the app policy's UTF-16 bound."""
    numeric_device(runtime_api)
    await setup(hass)
    with pytest.raises(HomeAssistantError, match="UTF-16"):
        await hass.services.async_call(
            "text", "set_value", {"entity_id": ENTITY, "value": "\U0001f63a" * 5}, blocking=True
        )
    runtime_api.set_device_alias.assert_not_awaited()


async def test_old_long_alias_can_be_displayed_and_replaced(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """The conservative write bound must not hide existing longer server aliases."""
    numeric_device(runtime_api)
    runtime_api.devices.return_value[0]["alias"] = EXPECTED_LEGACY_NAME
    await setup(hass)
    entity_id = next(state.entity_id for state in hass.states.async_all("text") if state.state == EXPECTED_LEGACY_NAME)
    await hass.services.async_call(
        "text", "set_value", {"entity_id": entity_id, "value": EXPECTED_ALIAS}, blocking=True
    )
    runtime_api.set_device_alias.assert_awaited_once_with("123", EXPECTED_ALIAS)


async def test_disappearing_device_is_unavailable(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A missing physical box cannot be renamed using retained state."""
    numeric_device(runtime_api)
    entry = await setup(hass)
    runtime_api.devices.return_value = []
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE
    runtime_api.set_device_alias.assert_not_awaited()


async def test_pet_records_have_no_cloud_alias_control(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Device aliases use a different contract from pet names."""
    numeric_device(runtime_api)
    await setup(hass)
    assert hass.states.get("text.test_cat_cloud_name") is None


async def test_app_rename_updates_cloud_field_and_registry_without_ha_override_loss(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """A rename made outside HA is reflected by polling while preserving local naming."""
    numeric_device(runtime_api)
    runtime_api.device_info.return_value["alias"] = "Old Info"
    entry = await setup(hass)
    registry = async_get_device_registry(hass)
    device = (
        registry.async_get_device_by_identifier(("notty", "123"), entry.entry_id)
        if hasattr(registry, "async_get_device_by_identifier")
        else registry.async_get_device(identifiers={("notty", "123")})
    )
    registry.async_update_device(device.id, name_by_user=EXPECTED_OVERRIDE)
    runtime_api.devices.return_value[0]["alias"] = EXPECTED_ALIAS
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_ALIAS
    assert registry.async_get(device.id).name == EXPECTED_ALIAS
    assert registry.async_get(device.id).name_by_user == EXPECTED_OVERRIDE
    runtime_api.set_device_alias.assert_not_awaited()


async def test_missing_alias_recovers_without_a_reload(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Missing or malformed cloud alias metadata stays unavailable until readback recovers."""
    numeric_device(runtime_api)
    runtime_api.devices.return_value[0]["alias"] = None
    entry = await setup(hass)
    unavailable = [
        state
        for state in hass.states.async_all("text")
        if state.state == EXPECTED_UNAVAILABLE and state.entity_id.endswith("_cloud_name")
    ]
    assert len(unavailable) == 1
    runtime_api.devices.return_value[0]["alias"] = EXPECTED_ALIAS
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(unavailable[0].entity_id).state == EXPECTED_ALIAS
    runtime_api.set_device_alias.assert_not_awaited()
