"""No-empty enforcement, independent app evidence and reversible write journals."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.notty.api import JsonObject, JsonValue, NottyApi, NottyApiError
from scripts import app_actions, app_validation
from scripts.probe_datapoints import write_json

EXPECTED_MATCH = "matches_supplied_phone_app_values"
EXPECTED_MISMATCH = "mismatch"
EXPECTED_PENDING = "pending_phone_app_values"
EXPECTED_RESTORED = "readback_matches_baseline"
PRIVATE_MODE = 0o600
GET = "GET"
PRIVATE_MARKER = "do-not-print"
POST = "POST"


@pytest.mark.parametrize("operation", [2, "2", True, 0, None, "empty", -1, 4])
async def test_empty_and_unknown_motor_commands_are_blocked_at_transport(operation: JsonValue) -> None:
    """Even a mistaken caller with writes enabled cannot send the empty code."""
    api = app_actions.ValidationApi(MagicMock())
    api.writes_enabled = True
    with patch.object(NottyApi, "request", AsyncMock()) as request, pytest.raises(NottyApiError, match="forbidden"):
        await api.request(POST, "/device/litter_box/one_key", data={"one_key": operation})
    request.assert_not_awaited()


async def test_read_mode_blocks_every_post() -> None:
    """The default transport is incapable of making a settings change."""
    api = app_actions.ValidationApi(MagicMock())
    with patch.object(NottyApi, "request", AsyncMock()) as request, pytest.raises(NottyApiError, match="explicit"):
        await api.request(POST, "/device/litter_box/set_key", data={"switch": 1})
    request.assert_not_awaited()


async def test_feature_cannot_route_another_features_write() -> None:
    """The lock script cannot disguise an unrelated command as a setting."""
    api = MagicMock()
    with pytest.raises(NottyApiError, match="Unsupported"):
        await app_actions.apply(api, "lock", app_actions.Target("123", "", {}), "set_mode", {"mode": 3})
    api.devices.assert_not_called()


def test_pending_or_api_copied_expectation_is_not_independent_app_verification() -> None:
    """Templates contain blanks and remain pending until explicitly filled from the app."""
    data: JsonObject = {"info": {"switch_key": 1}}
    expected = app_validation.template("lock", data)
    assert expected["checks"][0]["equals"] is None
    assert app_validation.app_comparison(data, expected, show_values=False)["status"] == EXPECTED_PENDING
    expected["checks"][0].update({"equals": 1, "confirmed_from_app": True})
    assert app_validation.app_comparison(data, expected, show_values=False)["status"] == EXPECTED_MATCH
    expected["checks"][0]["equals"] = True
    assert app_validation.app_comparison(data, expected, show_values=False)["status"] == EXPECTED_MISMATCH


def test_missing_field_never_matches_an_expected_null() -> None:
    """Missing API fields must not be confused with an actual null value."""
    expected: JsonObject = {
        "checks": [{"source": "info", "path": ["absent"], "equals": None, "confirmed_from_app": True}]
    }
    assert app_validation.app_comparison({"info": {}}, expected, show_values=False)["status"] == EXPECTED_MISMATCH


async def test_roundtrip_records_changed_readback_and_restores_original_on_success(tmp_path: Path) -> None:
    """A lock test stores separate phases and validates the original switch readback."""
    api = MagicMock()
    api.pets = AsyncMock(return_value=[])
    api.user_devices = AsyncMock(return_value=[])
    state: JsonObject = {"switch_key": 0}

    async def apply(_api: object, _feature: str, _target: object, _operation: str, changes: JsonObject) -> None:
        state["switch_key"] = changes["switch"]
        await asyncio.sleep(0)

    async def collect(
        _api: object, _feature: str, _target: object, _memo: object
    ) -> tuple[JsonObject, list[JsonValue]]:
        snapshot = deepcopy(state)
        await passthrough()
        return {"info": snapshot}, []

    request = tmp_path / "request.private.json"
    before = tmp_path / "before.private.json"
    write_json(request, {"operation": "set_key", "changes": {"switch": 1}})
    options = app_validation.Options(
        session_file=tmp_path / "session.private.json", execute=request, capture_raw=before, roundtrip=True
    )
    with (
        patch.object(app_actions, "apply", side_effect=apply),
        patch.object(app_validation, "collect", side_effect=collect),
    ):
        result = await app_validation.execute(
            api, "lock", app_actions.Target("123", "", {}), {"data": {"info": {"switch_key": 0}}, "errors": []}, options
        )
    assert state["switch_key"] == 0
    assert result["restore_status"] == EXPECTED_RESTORED
    after = app_validation.private_json(app_validation.phase_path(before, "after"))
    assert after["data"]["info"]["switch_key"] == 1
    restored_file = app_validation.phase_path(before, "restored")
    assert restored_file.stat().st_mode & 0o777 == PRIVATE_MODE


async def passthrough() -> None:
    """Yield to exercise asynchronous readback and restoration sequencing."""
    await asyncio.sleep(0)


async def test_roundtrip_restores_after_an_uncertain_write_failure(tmp_path: Path) -> None:
    """A timeout may follow an accepted write; restoration still runs once."""
    api = MagicMock()
    request = tmp_path / "request.private.json"
    write_json(request, {"operation": "set_key", "changes": {"switch": 1}})
    options = app_validation.Options(execute=request, capture_raw=tmp_path / "before.private.json", roundtrip=True)
    with (
        patch.object(app_actions, "apply", AsyncMock(side_effect=[NottyApiError("timeout"), None])) as apply,
        patch.object(app_validation, "collect", AsyncMock(return_value=({"info": {"switch_key": 0}}, []))),
        pytest.raises(NottyApiError, match="timeout"),
    ):
        await app_validation.execute(
            api, "lock", app_actions.Target("123", "", {}), {"data": {"info": {"switch_key": 0}}, "errors": []}, options
        )
    assert apply.await_args_list[-1].args[-1] == {"switch": 0}
    assert app_validation.phase_path(options.capture_raw, "restored").exists()


@pytest.mark.parametrize("feature", ["firmware", "statistics", "commands", "memos", "timezone"])
def test_nonrestorable_operations_cannot_start_a_roundtrip(feature: str) -> None:
    """History deletion, motor actions and firmware cannot be presented as reversible."""
    with pytest.raises(NottyApiError, match="restoration"):
        app_actions.restore_request(feature, "install", {}, {})


async def test_offline_comparison_uses_no_session_and_hides_private_values(tmp_path: Path) -> None:
    """A phone-app comparison can be rerun later without contacting NOTTY."""
    capture = tmp_path / "lock.private.json"
    expected = tmp_path / "app.private.json"
    write_json(capture, {"feature": "lock", "data": {"info": {"switch_key": 1, "token": "do-not-print"}}, "errors": []})
    write_json(
        expected, {"checks": [{"source": "info", "path": ["switch_key"], "equals": 1, "confirmed_from_app": True}]}
    )
    with patch.object(app_validation.aiohttp, "ClientSession", side_effect=AssertionError("network")):
        result = await app_validation.run("lock", app_validation.Options(from_file=capture, expect=expected))
    assert result["app_comparison"]["status"] == EXPECTED_MATCH
    assert PRIVATE_MARKER not in json.dumps(result)


def test_acknowledged_but_unchanged_api_write_is_a_mismatch() -> None:
    """HTTP success cannot hide a lock value that never changed in readback."""
    capture: JsonObject = {"request": {"operation": "set_key", "changes": {"switch": 1}}}
    assert app_validation.write_readback("lock", capture, {"info": {"switch_key": 0}}) == EXPECTED_MISMATCH
    assert app_validation.write_readback("lock", capture, {"info": {"switch_key": 1}}) != EXPECTED_MISMATCH


async def test_delayed_readback_polls_without_repeating_the_write() -> None:
    """An asynchronous device acknowledgement can settle after the first GET."""
    api = MagicMock()
    request: JsonObject = {"operation": "set_key", "changes": {"switch": 1}}
    snapshots = [({"info": {"switch_key": 0}}, []), ({"info": {"switch_key": 1}}, [])]
    with patch.object(app_validation, "collect", AsyncMock(side_effect=snapshots)) as collect:
        data, errors = await app_validation.read_until_applied(
            api, "lock", app_actions.Target("123", "", {}), request, app_validation.Options(readback_interval=0)
        )
    assert data["info"]["switch_key"] == 1
    assert errors == []
    assert collect.await_count == len(snapshots)
    api.request.assert_not_called()


async def test_final_readback_mismatch_is_not_hidden_by_polling() -> None:
    """Exhausting GET attempts retains the failed requested-value comparison."""
    request: JsonObject = {"operation": "set_key", "changes": {"switch": 1}}
    with patch.object(app_validation, "collect", AsyncMock(return_value=({"info": {"switch_key": 0}}, []))):
        data, _ = await app_validation.read_until_applied(
            MagicMock(), "lock", app_actions.Target("123", "", {}), request, app_validation.Options(readback_attempts=1)
        )
    assert app_validation.write_readback("lock", {"request": request}, data) == EXPECTED_MISMATCH


@pytest.mark.parametrize("switch", [True, "1", 1.0, -1, 2, None])
async def test_child_lock_rejects_non_app_switch_encodings(switch: JsonValue) -> None:
    """The integer enum is not a loosely coerced Boolean/string."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="integer switch"):
        await api.litter_action("123", "set_key", {"switch": switch})
    api.request.assert_not_awaited()
