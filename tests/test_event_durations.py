"""Observed NOTTY event formats, using invented cats and IDs."""

from __future__ import annotations

import pytest

from custom_components.notty.coordinator import litter_related_summary, toilet_event_summary

EXPECTED_SAMPLE_CAT = "Sample cat"
EXPECTED_2026_10_16T07_53_02_00 = "2026-10-16T07:53+02:00"
EXPECTED_LATEST_TOILET_EVENT_DURATION = "latest_toilet_event_duration"


@pytest.mark.parametrize(
    ("phrase", "seconds"),
    [
        ("Sample cat just spent 42s in the litter box.", 42),
        ("Sample cat just spent 38s in the litter box.", 38),
        ("Sample cat just spent 2m 3s in the litter box.", 123),
        ("Sample cat just spent 1m in the litter box.", 60),
    ],
)
def test_toilet_event_duration_formats(phrase: str, seconds: int | None) -> None:
    """Verify toilet event duration formats."""
    summary = toilet_event_summary({"event": phrase, "date": "2026-10-16", "time": "13:53"}, "Europe/Amsterdam")
    assert summary["latest_toilet_event_pet_name"] == EXPECTED_SAMPLE_CAT
    assert summary["latest_toilet_event_duration"] == seconds
    assert summary["latest_toilet_event_datetime"] == EXPECTED_2026_10_16T07_53_02_00


def test_unrecognized_duration_is_not_fabricated() -> None:
    """Verify unrecognized duration is not fabricated."""
    summary = toilet_event_summary(
        {"event": "Sample cat used litter box", "date": "2026-10-16", "time": "13:53"}, "Europe/Amsterdam"
    )
    assert EXPECTED_LATEST_TOILET_EVENT_DURATION not in summary


def test_server_event_and_utc_message_agree_in_amsterdam() -> None:
    """Verify server event and utc message agree in amsterdam."""
    related_summary = litter_related_summary(
        {"messages": {"date_created": "2026-10-16 13:53:45", "date_created_utc": "2026-10-16 05:53:45"}},
        "Europe/Amsterdam",
    )
    assert related_summary["messages_date_created"] == EXPECTED_2026_10_16T07_53_02_00
    event_summary = toilet_event_summary(
        {"event": "Sample cat just spent 42s in the litter box.", "date": "2026-10-16", "time": "13:53"},
        "Europe/Amsterdam",
    )
    assert event_summary["latest_toilet_event_datetime"] == EXPECTED_2026_10_16T07_53_02_00
