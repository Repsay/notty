"""Read-only firmware behavior from independently recorded APK metadata fields."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
import pytest

from custom_components.notty.api import NottyApi, NottyApiError
from custom_components.notty.update import firmware_version
from tests.test_lifecycle import setup

CONTRACT = json.loads((Path(__file__).parent / "fixtures/apk_firmware.json").read_text())
ENTITY = "update.test_box_firmware"
EXPECTED_ON = "on"
EXPECTED_OFF = "off"
EXPECTED_UNAVAILABLE = "unavailable"
EXPECTED_INSTALLED = "1.0.0"
EXPECTED_LATEST = "1.1.0"
EXPECTED_SUMMARY_LIMIT = 255
PRIVATE_VALUE = "synthetic-private"
FIELD_TASK_ID = "task_id"
EXPECTED_UNIQUE_ID = "box-1_firmware"
INTEGRATION_DOMAIN = "notty"
UPDATE_DOMAIN = "update"


async def test_firmware_entity_reports_app_fields(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Report offered versions and notes without exposing task IDs or arbitrary fields."""
    runtime_api.litter_related_info.return_value["upgrade"] = {**CONTRACT["offered"], "token": "synthetic-private"}
    await setup(hass)
    entity = hass.states.get(ENTITY)
    assert entity.state == EXPECTED_ON
    assert entity.attributes["installed_version"] == EXPECTED_INSTALLED
    assert entity.attributes["latest_version"] == EXPECTED_LATEST
    assert entity.attributes["release_summary"] == CONTRACT["offered"]["firmware_desc"]
    assert entity.attributes["task_status"] == CONTRACT["offered"]["task_status"]
    assert entity.attributes["supported_features"] == 0
    assert entity.attributes.get("update_percentage") is None
    assert PRIVATE_VALUE not in json.dumps(dict(entity.attributes))
    assert FIELD_TASK_ID not in entity.attributes
    registry = async_get_entity_registry(hass)
    registered = registry.async_get(ENTITY)
    assert registered.unique_id == EXPECTED_UNIQUE_ID
    assert registered.entity_category is EntityCategory.DIAGNOSTIC
    runtime_api.command.assert_not_awaited()
    runtime_api.litter_action.assert_not_awaited()


async def test_explicit_empty_destination_means_current(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """The app's empty target marker means no offered firmware, not an empty version."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["current"].copy()
    await setup(hass)
    entity = hass.states.get(ENTITY)
    assert entity.state == EXPECTED_OFF
    assert entity.attributes["latest_version"] == entity.attributes["installed_version"]


@pytest.mark.parametrize("destination", [None, False, 1, [], {}, " "])
async def test_malformed_destination_never_reports_up_to_date(
    hass: HomeAssistant, runtime_api: MagicMock, destination: object
) -> None:
    """Unknown target versions cannot be silently replaced with the installed version."""
    runtime_api.litter_related_info.return_value["upgrade"] = {**CONTRACT["offered"], "dest_version": destination}
    await setup(hass)
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE


@pytest.mark.parametrize("value", [None, False, 1, [], {}, "", " ", "1.0\n.0", "v" * 256])
def test_invalid_installed_versions_are_unknown(value: object) -> None:
    """Do not invent firmware versions from unrelated JSON or malformed text."""
    assert firmware_version(value) is None


async def test_latest_version_can_be_an_opaque_or_recovery_target(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Use the cloud's offered target rather than impose semantic version ordering."""
    runtime_api.litter_related_info.return_value["upgrade"] = {"src_version": "build-B", "dest_version": "build-A"}
    await setup(hass)
    assert hass.states.get(ENTITY).state == EXPECTED_ON


@pytest.mark.parametrize("status", ["IN_PROGRESS", "FAILED", "CANCELED", "SUCCEEDED", "future-status"])
async def test_raw_task_status_does_not_fabricate_progress_or_success(
    hass: HomeAssistant, runtime_api: MagicMock, status: str
) -> None:
    """HTTP metadata is not the app's separate live progress/event stream."""
    runtime_api.litter_related_info.return_value["upgrade"] = {
        **CONTRACT["offered"],
        "task_status": status,
        "step": "50",
    }
    await setup(hass)
    entity = hass.states.get(ENTITY)
    assert entity.attributes["task_status"] == status
    assert entity.attributes["installed_version"] == EXPECTED_INSTALLED
    assert entity.attributes.get("update_percentage") is None
    assert entity.state == EXPECTED_ON


async def test_completed_update_requires_fresh_version_readback(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Only a later check response can establish the new installed version."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    entry = await setup(hass)
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["current"].copy()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_OFF
    assert hass.states.get(ENTITY).attributes["installed_version"] == EXPECTED_LATEST


async def test_optional_endpoint_loss_and_recovery(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Do not continue reporting stale update availability after optional endpoint failure."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    entry = await setup(hass)
    runtime_api.litter_related_info.return_value.pop("upgrade")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["current"].copy()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_OFF


async def test_late_metadata_creates_one_entity(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """An unavailable optional endpoint at startup does not require a reload to recover."""
    entry = await setup(hass)
    assert hass.states.get(ENTITY) is None
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_ON
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    registry = async_get_entity_registry(hass)
    assert (
        len([
            item
            for item in registry.entities.values()
            if item.platform == INTEGRATION_DOMAIN and item.domain == UPDATE_DOMAIN
        ])
        == 1
    )
    await hass.config_entries.async_unload(entry.entry_id)
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE


@pytest.mark.parametrize("flag", [False, 0, "0", "false", "offline"])
async def test_explicit_offline_device_is_unavailable(
    hass: HomeAssistant, runtime_api: MagicMock, flag: object
) -> None:
    """Upgrade data cannot make an explicitly offline device look available."""
    runtime_api.device_info.return_value["online"] = flag
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    await setup(hass)
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE


async def test_disappearing_device_is_unavailable(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Coordinator removal invalidates firmware availability too."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    entry = await setup(hass)
    runtime_api.devices.return_value = []
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE


async def test_release_summary_is_bounded(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Limit the state attribute without loading arbitrary external release URLs."""
    runtime_api.litter_related_info.return_value["upgrade"] = {**CONTRACT["offered"], "firmware_desc": "a" * 1000}
    await setup(hass)
    assert len(hass.states.get(ENTITY).attributes["release_summary"]) == EXPECTED_SUMMARY_LIMIT


async def test_ha_install_service_cannot_start_firmware(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Read-only availability must not advertise or execute installation."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    await setup(hass)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    runtime_api.litter_action.assert_not_awaited()
    runtime_api.endpoint_action.assert_not_awaited()
    runtime_api.command.assert_not_awaited()


async def test_generic_api_cannot_confirm_an_unverified_upgrade() -> None:
    """Remove the formerly listed unchecked installation endpoint from the generic API."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="Unsupported litter box action"):
        await api.litter_action("synthetic-box", "confirm_upgrade", CONTRACT["confirmation"]["payload"])
    api.request.assert_not_awaited()


async def test_partial_metadata_does_not_reuse_previous_versions(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A response missing the target field cannot keep a stale offered update."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    entry = await setup(hass)
    runtime_api.litter_related_info.return_value["upgrade"] = {"src_version": "1.0.0"}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE


async def test_failed_coordinator_update_is_unavailable(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A transport failure invalidates otherwise retained upgrade metadata."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    entry = await setup(hass)
    runtime_api.devices.side_effect = NottyApiError("offline")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == EXPECTED_UNAVAILABLE


async def test_pet_and_other_product_records_do_not_receive_update_entities(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """Keep the current firmware scope limited to supported physical litter boxes."""
    runtime_api.litter_related_info.return_value["upgrade"] = CONTRACT["offered"].copy()
    runtime_api.devices.return_value.append({"user_device_id": "feeder-1", "device_type": "feeder", "alias": "Feeder"})
    await setup(hass)
    assert hass.states.get("update.test_cat_firmware") is None
    assert hass.states.get("update.feeder_firmware") is None
    assert hass.states.get(ENTITY).state == EXPECTED_ON
