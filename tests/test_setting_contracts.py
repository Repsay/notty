"""Synthetic contracts from APK 1.1.30; no cloud or hardware requests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.notty.api import NottyApi, NottyApiError, dnd_payload

DND_STATE = {"switch_dnd": 1, "led": 2, "dnd_begin_time": "22:00", "dnd_end_time": "07:00"}


@pytest.mark.parametrize("led", [0, 1, 2, "0"])
@pytest.mark.parametrize("enabled", [0, 1, "0", "1", False, True])
async def test_dnd_request_contract(led: int | str, *, enabled: int | str | bool) -> None:
    """Verify dnd request contract."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    current = {**DND_STATE, "led": led, "switch_dnd": enabled}
    before = current.copy()
    await api.litter_action("box-1", "set_dnd", dnd_payload(current))
    api.request.assert_awaited_once_with(
        "POST",
        "/device/litter_box/set_dnd",
        data={
            "user_device_id": "box-1",
            "device_id": "box-1",
            "switch": int(enabled),
            "led": led,
            "dnd_begin_time": "22:00",
            "dnd_end_time": "07:00",
        },
    )
    assert current == before


@pytest.mark.parametrize(
    "changes",
    [
        {"switch_dnd": None},
        {"switch_dnd": "unknown"},
        {"switch_dnd": 1.0},
        {"led": None},
        {"led": ""},
        {"led": {}},
        {"led": "unknown"},
        {"led": -1},
        {"dnd_begin_time": None},
        {"dnd_end_time": "25:00"},
        {"dnd_end_time": "07:00:30"},
        {"dnd_end_time": "07:00+02:00"},
        {"dnd_end_time": "22:00"},
    ],
)
def test_dnd_refuses_unknown_or_invalid_settings(changes: dict[str, object]) -> None:
    """Verify dnd refuses unknown or invalid settings."""
    with pytest.raises(NottyApiError):
        dnd_payload(DND_STATE, **changes)


def test_disabling_dnd_allows_existing_equal_times() -> None:
    """Verify disabling dnd allows existing equal times."""
    assert dnd_payload(DND_STATE, switch_dnd=0, dnd_end_time="22:00")["switch"] == 0


def test_editing_time_preserves_disabled_switch_and_led_zero() -> None:
    """Verify editing time preserves disabled switch and led zero."""
    assert dnd_payload({**DND_STATE, "switch_dnd": 0, "led": 0}, dnd_begin_time="00:00") == {
        "switch": 0,
        "led": 0,
        "dnd_begin_time": "00:00",
        "dnd_end_time": "07:00",
    }


@pytest.mark.parametrize("enabled", [0, 1])
async def test_child_lock_request_contract(*, enabled: int | str | bool) -> None:
    """Verify child lock request contract."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    await api.litter_action("box-1", "set_key", {"switch": enabled})
    api.request.assert_awaited_once_with(
        "POST", "/device/litter_box/set_key", data={"user_device_id": "box-1", "device_id": "box-1", "switch": enabled}
    )


@pytest.mark.parametrize("delay", [1, 15])
async def test_cleaning_delay_write_contract(delay: object) -> None:
    """Verify cleaning delay write contract."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    await api.litter_action("box-1", "set_auto_delay", {"delay": delay})
    api.request.assert_awaited_once_with(
        "POST",
        "/device/litter_box/set_auto_delay",
        data={"user_device_id": "box-1", "device_id": "box-1", "delay": delay},
    )


@pytest.mark.parametrize("delay", [0, 16, -1, 1.5, True, "5", None])
async def test_cleaning_delay_rejects_values_outside_app_contract(delay: object) -> None:
    """Verify cleaning delay rejects values outside app contract."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="1 to 15 minutes"):
        await api.litter_action("box-1", "set_auto_delay", {"delay": delay})
    api.request.assert_not_awaited()
