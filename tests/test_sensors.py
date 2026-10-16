import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfMass, UnitOfTime

from custom_components.notty.coordinator import (
    _format_local_datetime,
    _litter_info_summary,
    _merge_chart_summary,
)
from custom_components.notty.sensor import _sensor_keys, _sensor_metadata


@pytest.mark.parametrize(
    "key,value,expected",
    [
        (
            "today_wc_duration",
            "45",
            (SensorDeviceClass.DURATION, UnitOfTime.SECONDS, SensorStateClass.MEASUREMENT),
        ),
        (
            "today_weight",
            "4.2",
            (SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS, SensorStateClass.MEASUREMENT),
        ),
        ("weight_unit", 1, (SensorDeviceClass.ENUM, None, None)),
        ("plan_times", "09:00, 18:00", (None, None, None)),
        ("latest_event_time", "10:30", (None, None, None)),
        ("unknown_duration", "10:30", (None, None, None)),
        ("today_wc_duration", "unknown", (None, None, None)),
    ],
)
def test_explicit_sensor_metadata(key, value, expected):
    assert _sensor_metadata(key, value) == expected


def test_exclude_secrets_settings_non_litter_and_long_states():
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
    assert _sensor_keys(block) == ["today_wc_count"]


@pytest.mark.parametrize(
    "date,expected",
    [
        ("2026-07-25", "2026-07-25T04:00+02:00"),
        ("2026-01-25", "2026-01-25T03:00+01:00"),
    ],
)
def test_server_time_conversion_respects_dst(date, expected):
    assert _format_local_datetime(date, "10:00", "Europe/Amsterdam")[2] == expected


def test_toilet_summary_uses_latest_toilet_event():
    summary = _litter_info_summary(
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
    assert summary["latest_event_time"] == "05:00"
    assert summary["latest_toilet_event_duration"] == 42


def test_chart_summary_ignores_nulls_and_booleans():
    summary = {}
    _merge_chart_summary(
        summary, "duration", {"values": [None, True, 10, 0, 30], "times": ["a", "b", "c", "d", "e"]}
    )
    assert summary["duration_total"] == 40
    assert summary["duration_nonzero_count"] == 2
    assert summary["duration_latest_nonzero_time"] == "e"
