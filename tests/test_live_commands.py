"""Safe, mocked checks for the session-based NOTTY command validation helper."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.validate_commands import ValidationError, action_payload, load_session, validate

EXPECTED_USER_1 = "user-1"


def make_api(*, status: int = 0, switch_key: int = 0, switch_dnd: int = 0) -> SimpleNamespace:
    """Make api.

    Returns:
        SimpleNamespace: The resulting make api.
    """
    info = {
        "user_device_id": 9999,
        "status_id": 1,
        "status": status,
        "switch_key": switch_key,
        "switch_dnd": switch_dnd,
        "led": 2,
        "dnd_begin_time": "10:00",
        "dnd_end_time": "12:00",
    }
    return SimpleNamespace(litter_info=AsyncMock(return_value=info), litter_action=AsyncMock())


async def test_status_is_read_only() -> None:
    """Verify status is read only."""
    api = make_api()
    assert await validate(api, device_id="9999", action="status", value=None, execute=False) == 0
    api.litter_action.assert_not_awaited()


async def test_dry_run_does_not_call_write_api() -> None:
    """Verify dry run does not call write api."""
    api = make_api()
    assert await validate(api, device_id="9999", action="child-lock", value="on", execute=False) == 0
    api.litter_action.assert_not_awaited()


async def test_real_write_requires_interactive_confirmation() -> None:
    """Verify real write requires interactive confirmation."""
    api = make_api()
    with pytest.raises(ValidationError, match="interactive"):
        await validate(api, device_id="9999", action="child-lock", value="on", execute=True, interactive=False)
    api.litter_action.assert_not_awaited()


async def test_wrong_confirmation_cannot_send_write() -> None:
    """Verify wrong confirmation cannot send write."""
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


async def test_executed_child_lock_write_reads_back_once() -> None:
    """Verify executed child lock write reads back once."""
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
    api.litter_action.assert_awaited_once_with("9999", "set_key", {"switch": 1})
    sleep.assert_awaited_once_with(4)


async def test_not_idle_prevents_write() -> None:
    """Verify not idle prevents write."""
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


def test_dnd_write_preserves_existing_window_and_rejects_zero_length() -> None:
    """Verify dnd write preserves existing window and rejects zero length."""
    assert action_payload("dnd", 0, {"led": 0, "dnd_begin_time": "10:00", "dnd_end_time": "12:00"}) == {
        "switch": 0,
        "led": 0,
        "dnd_begin_time": "10:00",
        "dnd_end_time": "12:00",
    }
    with pytest.raises(ValidationError, match="identical"):
        action_payload("dnd", 1, {"led": 2, "dnd_begin_time": "00:00", "dnd_end_time": "00:00"})


async def test_dnd_missing_led_prevents_even_a_planned_write() -> None:
    """Verify dnd missing led prevents even a planned write."""
    api = make_api()
    api.litter_info.return_value.pop("led")
    with pytest.raises(ValidationError, match="LED"):
        await validate(api, device_id="9999", action="dnd", value="off", execute=False)
    api.litter_action.assert_not_awaited()


async def test_device_id_mismatch_stops_before_any_write() -> None:
    """Verify device id mismatch stops before any write."""
    api = make_api()
    with pytest.raises(ValidationError, match="mismatch"):
        await validate(api, device_id="9998", action="child-lock", value="on", execute=True)
    api.litter_action.assert_not_awaited()


def test_saved_session_requires_private_permissions(tmp_path: Path) -> None:
    """Verify saved session requires private permissions."""
    path = tmp_path / "session.private.json"
    path.write_text(json.dumps({"access_token": "not-a-real-token", "user_id": "user-1", "region_code": "NL"}))
    path.chmod(0o600)
    assert load_session(path)["user_id"] == EXPECTED_USER_1
    path.chmod(0o644)
    with pytest.raises(ValidationError, match="permissions"):
        load_session(path)
