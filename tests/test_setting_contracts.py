"""Synthetic contracts from APK 1.1.30; no cloud or hardware requests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.notty.api import NottyApi, NottyApiError, dnd_local_time, dnd_payload

DND_STATE = {
    "switch_dnd": 1,
    "led": 2,
    "dnd_begin_time": "22:00",
    "dnd_end_time": "07:00",
    "time_zone_iana": "Asia/Shanghai",
}


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


@pytest.mark.parametrize(
    ("when", "expected_start", "expected_end"),
    [
        (datetime(2026, 10, 16, 12, tzinfo=UTC), "07:00", "22:00"),
        (datetime(2026, 11, 16, 12, tzinfo=UTC), "06:00", "21:00"),
    ],
)
def test_dnd_readback_to_ha_handles_dst(
    when: datetime, expected_start: str, expected_end: str
) -> None:
    """Convert Shanghai read clocks into Amsterdam, including winter time."""
    start = dnd_local_time("13:00", "Europe/Amsterdam", at=when)
    end = dnd_local_time("04:00", "Europe/Amsterdam", at=when)
    assert start.strftime("%H:%M") == expected_start
    assert end.strftime("%H:%M") == expected_end


def test_dnd_device_timezone_wins_over_fallback() -> None:
    """A reported NOTTY timezone takes priority over the HA fallback."""
    current = {
        **DND_STATE,
        "time_zone_iana": "Europe/Amsterdam",
        "dnd_begin_time": "13:00",
        "dnd_end_time": "04:00",
    }
    result = dnd_payload(
        current, time_zone="UTC", at=datetime(2026, 10, 16, 12, tzinfo=UTC)
    )
    assert result == {
        "switch": 1,
        "led": 2,
        "dnd_begin_time": "07:00",
        "dnd_end_time": "22:00",
    }


def test_dnd_ha_edit_to_other_notty_device_timezone() -> None:
    """Edited HA clocks convert to the NOTTY device zone; preserved data also does."""
    current = {
        **DND_STATE,
        "time_zone_iana": "America/New_York",
        "dnd_begin_time": "13:00",
        "dnd_end_time": "04:00",
    }
    result = dnd_payload(
        current,
        time_zone="Europe/Amsterdam",
        input_time_zone="Europe/Amsterdam",
        at=datetime(2026, 10, 16, 12, tzinfo=UTC),
        dnd_begin_time="08:00",
    )
    assert result == {
        "switch": 1,
        "led": 2,
        "dnd_begin_time": "02:00",
        "dnd_end_time": "16:00",
    }


def test_dnd_missing_or_invalid_device_timezone_refuses_write() -> None:
    """Never guess a timezone from unverified account region or IP location."""
    for configured in (None, "Not/AZone"):
        current = {**DND_STATE}
        current.pop("time_zone_iana")
        if configured:
            current["time_zone_iana"] = configured
        with pytest.raises(NottyApiError, match="timezone"):
            dnd_payload(current)


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
