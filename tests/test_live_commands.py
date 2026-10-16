"""Safe, mocked checks for the session-based NOTTY command validation helper."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.validate_commands import (
    ValidationError,
    action_payload,
    load_session,
    validate,
)


def make_api(*, status=0, switch_key=0, switch_dnd=0):
    info = {
        "user_device_id": 9999,
        "status_id": 1,
        "status": status,
        "switch_key": switch_key,
        "switch_dnd": switch_dnd,
        "dnd_begin_time": "10:00",
        "dnd_end_time": "12:00",
    }
    return SimpleNamespace(
        litter_info=AsyncMock(return_value=info),
        litter_action=AsyncMock(),
    )


async def test_status_is_read_only():
    api = make_api()
    assert (
        await validate(api, device_id="9999", action="status", value=None, execute=False)
        == 0
    )
    api.litter_action.assert_not_awaited()


async def test_dry_run_does_not_call_write_api():
    api = make_api()
    assert (
        await validate(
            api, device_id="9999", action="child-lock", value="on", execute=False
        )
        == 0
    )
    api.litter_action.assert_not_awaited()


async def test_real_write_requires_interactive_confirmation():
    api = make_api()
    with pytest.raises(ValidationError, match="interactive"):
        await validate(
            api,
            device_id="9999",
            action="child-lock",
            value="on",
            execute=True,
            interactive=False,
        )
    api.litter_action.assert_not_awaited()


async def test_wrong_confirmation_cannot_send_write():
    api = make_api()
    with pytest.raises(ValidationError, match="Confirmation"):
        await validate(
            api,
            device_id="9999",
            action="child-lock",
            value="on",
            execute=True,
            interactive=True,
            ask=lambda _: "WRONG",
        )
    api.litter_action.assert_not_awaited()


async def test_executed_child_lock_write_reads_back_once():
    api = make_api()
    after = dict(await api.litter_info("9999"), switch_key=1)
    api.litter_info = AsyncMock(side_effect=[make_api().litter_info.return_value, after])
    sleep = AsyncMock()
    result = await validate(
        api,
        device_id="9999",
        action="child-lock",
        value="on",
        execute=True,
        interactive=True,
        ask=lambda _: "WRITE 9999 child-lock on",
        sleep=sleep,
    )
    assert result == 0
    api.litter_action.assert_awaited_once_with("9999", "set_key", {"switch_key": 1})
    sleep.assert_awaited_once_with(4)


async def test_not_idle_prevents_write():
    api = make_api(status=2)
    with pytest.raises(ValidationError, match="not idle"):
        await validate(
            api,
            device_id="9999",
            action="child-lock",
            value="off",
            execute=True,
            interactive=True,
            ask=lambda _: "WRITE 9999 child-lock off",
        )
    api.litter_action.assert_not_awaited()


def test_dnd_write_preserves_existing_window_and_rejects_zero_length():
    assert action_payload(
        "dnd",
        0,
        {"dnd_begin_time": "10:00", "dnd_end_time": "12:00"},
    ) == {
        "switch_dnd": 0,
        "dnd_begin_time": "10:00",
        "dnd_end_time": "12:00",
    }
    with pytest.raises(ValidationError, match="identical"):
        action_payload(
            "dnd",
            1,
            {"dnd_begin_time": "00:00", "dnd_end_time": "00:00"},
        )


async def test_device_id_mismatch_stops_before_any_write():
    api = make_api()
    with pytest.raises(ValidationError, match="mismatch"):
        await validate(
            api,
            device_id="9998",
            action="child-lock",
            value="on",
            execute=True,
        )
    api.litter_action.assert_not_awaited()


def test_saved_session_requires_private_permissions(tmp_path):
    path = tmp_path / "session.private.json"
    path.write_text(
        json.dumps(
            {
                "access_token": "not-a-real-token",
                "user_id": "user-1",
                "region_code": "NL",
            }
        )
    )
    path.chmod(0o600)
    assert load_session(path)["user_id"] == "user-1"
    path.chmod(0o644)
    with pytest.raises(ValidationError, match="permissions"):
        load_session(path)
