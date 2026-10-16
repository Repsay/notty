"""Observed NOTTY event formats, using invented cats and IDs."""

import pytest

from custom_components.notty.coordinator import (
    _litter_related_summary,
    _toilet_event_summary,
)


@pytest.mark.parametrize(
    "phrase,seconds",
    [
        ("Sample cat just spent 42s in the litter box.", 42),
        ("Sample cat just spent 38s in the litter box.", 38),
        ("Sample cat just spent 2m 3s in the litter box.", 123),
        ("Sample cat just spent 1m in the litter box.", 60),
    ],
)
def test_toilet_event_duration_formats(phrase, seconds):
    summary = _toilet_event_summary(
        {"event": phrase, "date": "2026-10-16", "time": "13:53"},
        "Europe/Amsterdam",
    )
    assert summary["latest_toilet_event_pet_name"] == "Sample cat"
    assert summary["latest_toilet_event_duration"] == seconds
    assert summary["latest_toilet_event_datetime"] == "2026-10-16T07:53+02:00"


def test_unrecognized_duration_is_not_fabricated():
    summary = _toilet_event_summary(
        {"event": "Sample cat used litter box", "date": "2026-10-16", "time": "13:53"},
        "Europe/Amsterdam",
    )
    assert "latest_toilet_event_duration" not in summary


def test_server_event_and_utc_message_agree_in_amsterdam():
    related_summary = _litter_related_summary(
        {
            "messages": {
                "date_created": "2026-10-16 13:53:45",
                "date_created_utc": "2026-10-16 05:53:45",
            }
        },
        "Europe/Amsterdam",
    )
    assert related_summary["messages_date_created"] == "2026-10-16T07:53+02:00"
    event_summary = _toilet_event_summary(
        {"event": "Sample cat just spent 42s in the litter box.", "date": "2026-10-16",
         "time": "13:53"},
        "Europe/Amsterdam",
    )
    assert event_summary["latest_toilet_event_datetime"] == "2026-10-16T07:53+02:00"
