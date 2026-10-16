"""Regression coverage for sparse NOTTY daily event histories."""

from __future__ import annotations

from datetime import date

from custom_components.notty.coordinator import litter_related_summary

EXPECTED_2026_10_16 = "2026-10-16"
EXPECTED_SUMMARY_LATEST_DAILY_EVENT_COUNT = 4
EXPECTED_SUMMARY_DAILY_EVENTS_TOTAL = 214
EXPECTED_SUMMARY_DAILY_EVENTS_LAST_7_DAYS = 9
EXPECTED_SUMMARY_DAILY_EVENTS_LAST_30_DAYS = 114
EXPECTED_SUMMARY_DAILY_EVENTS_AVERAGE = 35.67
EXPECTED_DAILY_EVENTS_LAST_30_DAYS = "daily_events_last_30_days"


def test_rolling_calendar_windows_handle_sparse_unsorted_history() -> None:
    """Verify rolling calendar windows handle sparse unsorted history."""
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
    summary = litter_related_summary({"daily_event_counts": rows}, "Europe/Amsterdam", today=date(2026, 10, 16))
    assert summary["latest_daily_event_date"] == EXPECTED_2026_10_16
    assert summary["latest_daily_event_count"] == EXPECTED_SUMMARY_LATEST_DAILY_EVENT_COUNT
    assert summary["daily_events_total"] == EXPECTED_SUMMARY_DAILY_EVENTS_TOTAL
    assert summary["daily_events_last_7_days"] == EXPECTED_SUMMARY_DAILY_EVENTS_LAST_7_DAYS
    assert summary["daily_events_last_30_days"] == EXPECTED_SUMMARY_DAILY_EVENTS_LAST_30_DAYS
    assert summary["daily_events_average"] == EXPECTED_SUMMARY_DAILY_EVENTS_AVERAGE


def test_no_valid_dates_does_not_invent_event_totals() -> None:
    """Verify no valid dates does not invent event totals."""
    summary = litter_related_summary(
        {"daily_event_counts": [{"year": 2026, "month": 13, "day": 1, "count": 5}]},
        "Europe/Amsterdam",
        today=date(2026, 10, 16),
    )
    assert EXPECTED_DAILY_EVENTS_LAST_30_DAYS not in summary
