"""DST boundary observations are checked as UTC instants without assuming device policy."""

from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

from scripts.validate_schedule_observation import Options, Schedule, occurrences, report, run

ZONE = "Europe/Amsterdam"
MATCH = "supplied_observation_matches"
MISMATCH = "supplied_observation_mismatch"
AMBIGUOUS = "ambiguous_local_time_choose_occurrence"
GAP = "nonexistent_local_time_device_policy_unverified"
PENDING = "pending_physical_observation"
PRIVATE_MODE = 0o600


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 3, 29), []),
        (date(2026, 10, 25), ["2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00+00:00"]),
        (date(2026, 10, 24), ["2026-10-24T00:30:00+00:00"]),
    ],
)
def test_european_gap_and_fold(day: date, expected: list[str]) -> None:
    """Nonexistent clocks have no candidate; repeated clocks have two distinct instants."""
    assert [instant.isoformat() for instant in occurrences(day, time(2, 30), ZONE)] == expected


def test_crossing_midnight_in_a_non_hour_offset_zone() -> None:
    """A device-local date may correspond to the preceding UTC date."""
    assert occurrences(date(2026, 10, 17), time(0, 15), "Asia/Kathmandu") == [
        datetime(2026, 10, 16, 18, 30, tzinfo=UTC)
    ]


@pytest.mark.parametrize(
    ("observed", "selection", "expected"),
    [
        (None, None, AMBIGUOUS),
        ("2026-10-25T02:30:00+02:00", None, AMBIGUOUS),
        ("2026-10-25T02:30:00+02:00", 1, MATCH),
        ("2026-10-25T02:30:00+01:00", 2, MATCH),
        ("2026-10-25T02:30:00+01:00", 1, MISMATCH),
    ],
)
def test_observation_selects_explicit_fold(observed: str | None, selection: int | None, expected: str) -> None:
    """The same wall clock with another UTC offset is a different scheduled occurrence."""
    result = report(
        Schedule(date(2026, 10, 25), time(2, 30), ZONE),
        observed_at=datetime.fromisoformat(observed) if observed else None,
        occurrence=selection,
    )
    assert result["status"] == expected


def test_gap_and_unobserved_schedule_never_pass() -> None:
    """Computing a calendar candidate is not physical validation."""
    assert report(Schedule(date(2026, 3, 29), time(2, 30), ZONE))["status"] == GAP
    assert report(Schedule(date(2026, 10, 17), time(8), ZONE))["status"] == PENDING


@pytest.mark.parametrize("tolerance", [-1, 301, float("nan"), float("inf")])
def test_unbounded_tolerance_rejected(tolerance: float) -> None:
    """A broad tolerance must not hide a timezone or date error."""
    with pytest.raises(ValueError, match="Tolerance"):
        report(Schedule(date(2026, 10, 17), time(8), ZONE), tolerance_seconds=tolerance)


def test_naive_observations_and_nonexistent_selection_rejected() -> None:
    """Never invent an observation's offset or a second occurrence on an ordinary day."""
    schedule = Schedule(date(2026, 10, 17), time(8), ZONE)
    with pytest.raises(ValueError, match="UTC offset"):
        report(schedule, observed_at=datetime(2026, 10, 17, 8, tzinfo=UTC).replace(tzinfo=None))
    with pytest.raises(ValueError, match="existing occurrence"):
        report(schedule, occurrence=2)
    with pytest.raises(ValueError, match="without an offset"):
        occurrences(schedule.day, time(8, tzinfo=UTC), ZONE)


def test_output_is_private_and_cannot_overwrite_evidence(tmp_path: Path) -> None:
    """Saved observation evidence is local and cannot replace an earlier report."""
    options = Options("2026-10-17", "08:00", ZONE, output=tmp_path / "observed.private.json")
    assert run(options)["status"] == PENDING
    assert options.output.stat().st_mode & 0o777 == PRIVATE_MODE
    with pytest.raises(ValueError, match="new file"):
        run(options)
