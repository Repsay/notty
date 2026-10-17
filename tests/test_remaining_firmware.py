"""Firmware requests survive reloads without replay or unrelated-task completion."""

from unittest.mock import MagicMock

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.notty.api import NottyApiError
from tests.test_device_features import UPGRADE
from tests.test_feature_ui import configure
from tests.test_lifecycle import setup

ENTITY = "update.test_box_firmware"
METHOD_POST = "POST"
CONFIRM = "/device/confirm_upgrade"


def confirmations(api: MagicMock) -> int:
    """Count only actual firmware confirmations.

    Returns:
        The number of firmware writes.
    """
    return sum(call.args[:2] == (METHOD_POST, CONFIRM) for call in api.request.await_args_list)


async def test_pending_install_survives_reload_without_replay(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Reloading uses persisted state, rejects duplicate installs and awaits version readback."""
    configure(runtime_api)
    runtime_api.litter_related_info.return_value["upgrade"] = dict(UPGRADE)
    entry = await setup(hass)
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    assert confirmations(runtime_api) == 1
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["in_progress"] is True
    assert state.attributes["supported_features"] & UpdateEntityFeature.PROGRESS
    assert not state.attributes["supported_features"] & UpdateEntityFeature.INSTALL
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    assert confirmations(runtime_api) == 1
    runtime_api.litter_related_info.return_value["upgrade"] = {
        **UPGRADE,
        "src_version": UPGRADE["dest_version"],
        "dest_version": "",
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["in_progress"] is False
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["in_progress"] is False
    assert confirmations(runtime_api) == 1


async def test_other_task_failure_does_not_finish_pending_install(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A changed task identity makes progress unknown, never claims failure or retries."""
    configure(runtime_api)
    runtime_api.litter_related_info.return_value["upgrade"] = dict(UPGRADE)
    entry = await setup(hass)
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    runtime_api.litter_related_info.return_value["upgrade"] = {
        **UPGRADE,
        "task_id": "other-task",
        "task_status": "FAILED",
    }
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.attributes["in_progress"] is None
    assert not state.attributes["supported_features"] & UpdateEntityFeature.INSTALL
    assert confirmations(runtime_api) == 1


async def test_timed_out_confirmation_remains_pending_after_reload(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """An uncertain POST cannot be replayed merely because the caller saw an error."""
    configure(runtime_api)
    original = runtime_api.request.side_effect

    def request(method: str, path: str, **kwargs: object) -> object:
        if method == METHOD_POST and path == CONFIRM:
            msg = "synthetic timeout"
            raise NottyApiError(msg)
        return original(method, path, **kwargs)

    runtime_api.request.side_effect = request
    runtime_api.litter_related_info.return_value["upgrade"] = dict(UPGRADE)
    entry = await setup(hass)
    with pytest.raises(HomeAssistantError, match="synthetic timeout"):
        await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["in_progress"] is True
    assert confirmations(runtime_api) == 1


async def test_stale_failure_needs_a_new_task_observation(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Retrying an eligible failed task does not immediately fail from its old cached status."""
    configure(runtime_api)
    runtime_api.litter_related_info.return_value["upgrade"] = {**UPGRADE, "task_status": "FAILED"}
    runtime_api.request.side_effect = lambda *_args, **_kwargs: {**UPGRADE, "task_status": "FAILED"}
    entry = await setup(hass)
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    assert hass.states.get(ENTITY).attributes["in_progress"] is True
    for status in ("IN_PROGRESS", "FAILED"):
        runtime_api.litter_related_info.return_value["upgrade"] = {**UPGRADE, "task_status": status}
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["in_progress"] is False
