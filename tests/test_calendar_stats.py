"""Regression coverage for sparse NOTTY daily event histories."""

from datetime import date

from custom_components.notty.coordinator import _litter_related_summary


def test_rolling_calendar_windows_handle_sparse_unsorted_history():
    rows = [
        {"year": 2026, "month": 10, "day": 9, "count": 100},
        {"year": 2026, "month": 10, "day": 16, "count": 4},
        {"year": 2026, "month": 9, "day": 16, "count": 100},
        {"year": 2026, "month": 10, "day": 10, "count": 2},
        {"year": 2026, "month": 9, "day": 17, "count": 5},
        {"year": 2026, "month": 10, "day": 15, "count": 3},
        {"year": 2026, "month": 10, "day": 17, "count": 999},
        {"year": 2026, "month": 2, "day": 30, "count": 999},
        {"year": 2026, "month": 10, "day": 14, "count": True},
        {"year": 2026, "month": 10, "day": 13},
        {"year": "unknown", "month": 10, "day": 12, "count": 100},
    ]
    summary = _litter_related_summary(
        {"daily_event_counts": rows},
        "Europe/Amsterdam",
        today=date(2026, 10, 16),
    )
    assert summary["latest_daily_event_date"] == "2026-10-16"
    assert summary["latest_daily_event_count"] == 4
    assert summary["daily_events_total"] == 214
    assert summary["daily_events_last_7_days"] == 9
    assert summary["daily_events_last_30_days"] == 114
    assert summary["daily_events_average"] == 35.67


def test_no_valid_dates_does_not_invent_event_totals():
    summary = _litter_related_summary(
        {"daily_event_counts": [{"year": 2026, "month": 13, "day": 1, "count": 5}]},
        "Europe/Amsterdam",
        today=date(2026, 10, 16),
    )
    assert "daily_events_last_30_days" not in summary
