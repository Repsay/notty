from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfMass, UnitOfTime
import pytest

from custom_components.notty.coordinator import format_local_datetime, litter_info_summary, merge_chart_summary
from custom_components.notty.sensor import sensor_keys, sensor_metadata

EXPECTED_05_00 = "05:00"
EXPECTED_SUMMARY_LATEST_TOILET_EVENT_DURATION = 42
EXPECTED_SUMMARY_DURATION_TOTAL = 40
EXPECTED_SUMMARY_DURATION_NONZERO_COUNT = 2
EXPECTED_E = "e"


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("today_wc_duration", "45", (SensorDeviceClass.DURATION, UnitOfTime.SECONDS, SensorStateClass.MEASUREMENT)),
        ("today_weight", "4.2", (SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS, SensorStateClass.MEASUREMENT)),
        ("weight_unit", 1, (SensorDeviceClass.ENUM, None, None)),
        ("plan_times", "09:00, 18:00", (None, None, None)),
        ("latest_event_time", "10:30", (None, None, None)),
        ("unknown_duration", "10:30", (None, None, None)),
        ("today_wc_duration", "unknown", (None, None, None)),
    ],
)
def test_explicit_sensor_metadata(key: str, value: object, expected: object) -> None:
    """Verify explicit sensor metadata."""
    assert sensor_metadata(key, value) == expected


def test_exclude_secrets_settings_non_litter_and_long_states() -> None:
    """Verify exclude secrets settings non litter and long states."""
    block = {
        "info": {
            "token": "secret",
            "mode": 1,
            "switch_key": "0",
            "today_eat_count": 5,
            "large": "x" * 256,
            "today_wc_count": 3,
            "nested": {"x": 1},
        }
    }
    assert sensor_keys(block) == ["today_wc_count"]


@pytest.mark.parametrize(
    ("date", "expected"), [("2026-07-25", "2026-07-25T04:00+02:00"), ("2026-01-25", "2026-01-25T03:00+01:00")]
)
def test_server_time_conversion_respects_dst(date: str, expected: object) -> None:
    """Verify server time conversion respects dst."""
    assert format_local_datetime(date, "10:00", "Europe/Amsterdam")[2] == expected


def test_toilet_summary_uses_latest_toilet_event() -> None:
    """Verify toilet summary uses latest toilet event."""
    summary = litter_info_summary(
        {
            "events": [
                {"event": "Cleaning", "event_type_id": 1, "date": "2026-07-25", "time": "11:00"},
                {
                    "event": "Test cat spent 42s in litter box",
                    "event_type_id": 12,
                    "date": "2026-07-25",
                    "time": "10:00",
                },
            ]
        },
        "Europe/Amsterdam",
    )
    assert summary["latest_event_time"] == EXPECTED_05_00
    assert summary["latest_toilet_event_duration"] == EXPECTED_SUMMARY_LATEST_TOILET_EVENT_DURATION


def test_chart_summary_ignores_nulls_and_booleans() -> None:
    """Verify chart summary ignores nulls and booleans."""
    summary = {}
    merge_chart_summary(summary, "duration", {"values": [None, True, 10, 0, 30], "times": ["a", "b", "c", "d", "e"]})
    assert summary["duration_total"] == EXPECTED_SUMMARY_DURATION_TOTAL
    assert summary["duration_nonzero_count"] == EXPECTED_SUMMARY_DURATION_NONZERO_COUNT
    assert summary["duration_latest_nonzero_time"] == EXPECTED_E
