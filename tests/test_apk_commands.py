"""Independent synthetic fixtures transcribed from UI callers and closure values."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
import pytest

from custom_components.notty.api import LITTER_MODES, NottyApi, NottyApiError
from custom_components.notty.button import BUTTONS
from custom_components.notty.validation import vol
from tests.test_lifecycle import setup

CONTRACT = json.loads((Path(__file__).parent / "fixtures/apk_litter_commands.json").read_text())
COMMANDS = CONTRACT["one_key"]
MODES = CONTRACT["mode"]
EXPECTED_NUMERIC_MODE = "Mode 99"
UNSUPPORTED_STERILIZE = "sterilize"


@pytest.mark.parametrize("fixture", COMMANDS, ids=[item["name"] for item in COMMANDS])
async def test_one_key_matches_app_serialization(fixture: dict[str, object]) -> None:
    """The named and numeric API paths serialize the transcribed integer value."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    for operation in (fixture["name"], fixture["payload"]["one_key"]):
        await api.command("synthetic-box", operation)
        api.request.assert_awaited_once_with("POST", "/device/litter_box/one_key", data=fixture["payload"])
        api.request.reset_mock()
        await api.litter_action("synthetic-box", "one_key", {"one_key": operation, "user_device_id": "other"})
        api.request.assert_awaited_once_with("POST", "/device/litter_box/one_key", data=fixture["payload"])
        api.request.reset_mock()


@pytest.mark.parametrize("operation", [None, 0, -1, 4, True, False, 1.0, "1", "sterilize", {}, []])
async def test_unknown_one_key_cannot_reach_cloud(operation: object) -> None:
    """Reject old guessed codes, unsupported labels and coercible non-integers."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="Unsupported litter-box one_key"):
        await api.command("synthetic-box", operation)
    with pytest.raises(NottyApiError, match="Unsupported litter-box one_key"):
        await api.litter_action("synthetic-box", "one_key", {"one_key": operation})
    api.request.assert_not_awaited()


async def test_other_product_codes_are_not_assumed() -> None:
    """Feeder/water contracts must not inherit litter-box numeric meanings."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="only established for litter boxes"):
        await api.command("synthetic-feeder", 1, "feeder")
    api.request.assert_not_awaited()


@pytest.mark.parametrize("fixture", COMMANDS, ids=[item["name"] for item in COMMANDS])
async def test_button_and_named_service_agree_with_app(
    hass: HomeAssistant, runtime_api: MagicMock, fixture: dict[str, object]
) -> None:
    """Both exposed paths use the mapping established independently in the APK."""
    await setup(hass)
    name = fixture["name"]
    entity_name = {"clean": "clean", "empty": "empty_litter", "level": "level_litter"}[name]
    await hass.services.async_call("button", "press", {"entity_id": f"button.test_box_{entity_name}"}, blocking=True)
    runtime_api.command.assert_awaited_once_with("box-1", fixture["payload"]["one_key"], "litter_box")
    runtime_api.command.reset_mock()
    await hass.services.async_call(
        "notty", "litter_box_one_key", {"user_device_id": "box-1", "one_key": name}, blocking=True
    )
    runtime_api.command.assert_awaited_once_with("box-1", fixture["payload"]["one_key"], "litter_box")


@pytest.mark.parametrize("operation", [0, 4, "sterilize", "1"])
async def test_unsupported_service_options_are_rejected(
    hass: HomeAssistant, runtime_api: MagicMock, operation: object
) -> None:
    """Remove the mistaken sterilize label and raw zero from public services."""
    await setup(hass)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "notty", "litter_box_one_key", {"user_device_id": "box-1", "one_key": operation}, blocking=True
        )
    runtime_api.command.assert_not_awaited()
    assert all(description.key != UNSUPPORTED_STERILIZE for description in BUTTONS)
    assert hass.states.get("button.test_box_sterilize") is None


@pytest.mark.parametrize("fixture", MODES, ids=[item["label"] for item in MODES])
async def test_mode_labels_follow_ui_callers(
    hass: HomeAssistant, runtime_api: MagicMock, fixture: dict[str, object]
) -> None:
    """Present traced labels and keep selecting the current mode a read-only no-op."""
    value = fixture["payload"]["mode"]
    runtime_api.device_info.return_value["mode"] = value
    await setup(hass)
    assert LITTER_MODES[value] == fixture["label"]
    assert hass.states.get("select.test_box_mode").state == fixture["label"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": "select.test_box_mode", "option": fixture["label"]}, blocking=True
    )
    runtime_api.litter_action.assert_not_awaited()


async def test_raw_mode_action_cannot_bypass_guard() -> None:
    """The lower-level API applies the same mode-write boundary as the select."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    api.litter_info = AsyncMock(return_value={"user_device_id": 123})
    for value in (1, 2, 3):
        with pytest.raises(NottyApiError, match="known current device mode"):
            await api.litter_action("123", "set_mode", {"mode": value})
    api.request.assert_not_awaited()


async def test_unrecognized_mode_retains_numeric_readback(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """A newer enum cannot silently acquire an existing label."""
    runtime_api.device_info.return_value["mode"] = 99
    await setup(hass)
    assert hass.states.get("select.test_box_mode").state == EXPECTED_NUMERIC_MODE
