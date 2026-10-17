#!/usr/bin/env python3
"""Compare an observed start with a selected device-local schedule occurrence.

Offline only: no device commands or timezone changes. This checks owner-supplied
observations, not whether the box will follow a particular DST policy. Ambiguous
and nonexistent local times are reported explicitly instead of silently shifted.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import json
import math
from pathlib import Path
import sys
from typing import cast
from zoneinfo import ZoneInfo

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.notty.api import JsonObject, JsonValue
from scripts.console import console
from scripts.probe_datapoints import write_json

MAX_TOLERANCE_SECONDS = 300


def occurrences(day: date, clock: time, zone: str) -> list[datetime]:
    """Resolve valid UTC instants, rejecting the zoneinfo normalization of DST gaps.

    Returns:
        Zero, one or two chronologically ordered UTC instants.

    Raises:
        ValueError: If the supplied wall clock includes a timezone.
    """
    if clock.tzinfo is not None:
        msg = "The scheduled clock must be a local time without an offset"
        raise ValueError(msg)
    wall = datetime.combine(day, clock)
    selected_zone = ZoneInfo(zone)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        instant = wall.replace(tzinfo=selected_zone, fold=fold).astimezone(UTC)
        if instant.astimezone(selected_zone).replace(tzinfo=None) == wall:
            candidates.add(instant)
    return sorted(candidates)


@dataclass(frozen=True)
class Schedule:
    """One device-local calendar occurrence, without assuming recurrence."""

    day: date
    clock: time
    zone: str


def report(
    schedule: Schedule,
    *,
    observed_at: datetime | None = None,
    occurrence: int | None = None,
    tolerance_seconds: float = 60,
) -> JsonObject:
    """Keep calendar analysis and supplied physical observation checks distinct.

    Returns:
        Expected UTC candidates and an explicit observation verdict.

    Raises:
        ValueError: If a timestamp is naive, tolerance is unbounded or an occurrence is invalid.
    """
    if not math.isfinite(tolerance_seconds) or not 0 <= tolerance_seconds <= MAX_TOLERANCE_SECONDS:
        msg = "Tolerance must be finite and between 0 and 300 seconds"
        raise ValueError(msg)
    candidates = occurrences(schedule.day, schedule.clock, schedule.zone)
    if occurrence is not None and (type(occurrence) is not int or not 1 <= occurrence <= len(candidates)):
        msg = "Select an existing occurrence, numbered 1 or 2 in UTC order"
        raise ValueError(msg)
    if observed_at is not None and (observed_at.tzinfo is None or observed_at.utcoffset() is None):
        msg = "Observed timestamps must include their actual UTC offset"
        raise ValueError(msg)
    status = "pending_physical_observation"
    delta: float | None = None
    if not candidates:
        status = "nonexistent_local_time_device_policy_unverified"
    elif len(candidates) > 1 and occurrence is None:
        status = "ambiguous_local_time_choose_occurrence"
    elif observed_at is not None:
        expected = candidates[(occurrence or 1) - 1]
        delta = (observed_at.astimezone(UTC) - expected).total_seconds()
        status = "supplied_observation_matches" if abs(delta) <= tolerance_seconds else "supplied_observation_mismatch"
    instants: list[JsonValue] = [instant.isoformat() for instant in candidates]
    return {
        "feature": "schedule_observation",
        "date": schedule.day.isoformat(),
        "local_time": schedule.clock.isoformat(),
        "time_zone": schedule.zone,
        "expected_utc_occurrences": instants,
        "selected_occurrence": occurrence,
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
        "difference_seconds": delta,
        "status": status,
        "limitations": "Uses the supplied schedule, date, zone and observed start. Does not establish recurrence, device DST policy, physical completion or official-app agreement. No API requests are made.",
    }


@dataclass
class Options:
    """Explicit offline schedule and independent observation inputs."""

    date: str
    local_time: str
    time_zone: str
    observed_at: str | None = None
    occurrence: int | None = None
    tolerance_seconds: float = 60
    output: Path | None = None


def run(options: Options) -> JsonObject:
    """Validate all inputs and optionally save an offline report.

    Returns:
        Expected instants and the observation verdict.

    Raises:
        ValueError: If an output already exists or date/clock inputs are invalid.
    """
    if options.output and (options.output.exists() or options.output.is_symlink()):
        msg = "Output must be a new file"
        raise ValueError(msg)
    result = report(
        Schedule(date.fromisoformat(options.date), time.fromisoformat(options.local_time), options.time_zone),
        observed_at=datetime.fromisoformat(options.observed_at) if options.observed_at else None,
        occurrence=options.occurrence,
        tolerance_seconds=options.tolerance_seconds,
    )
    if options.output:
        write_json(options.output, result)
    return result


def main() -> int:
    """Resolve one calendar occurrence without changing a device setting.

    Returns:
        Zero for a supplied matching observation, one for mismatch, two for invalid inputs, three for pending/ambiguous.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Device-local calendar date, YYYY-MM-DD")
    parser.add_argument("--local-time", required=True, help="Scheduled device-local clock, HH:MM")
    parser.add_argument("--time-zone", required=True, help="IANA zone read from the device, e.g. Europe/Amsterdam")
    parser.add_argument(
        "--observed-at", help="Independently observed physical start, ISO timestamp including UTC offset"
    )
    parser.add_argument(
        "--occurrence", type=int, choices=(1, 2), help="Select the first or second occurrence on a DST fold"
    )
    parser.add_argument("--tolerance-seconds", type=float, default=60)
    parser.add_argument("--output", type=Path)
    options = cast("Options", parser.parse_args())
    try:
        result = run(options)
        console(json.dumps(result, indent=2, allow_nan=False))
    except OSError, ValueError, KeyError:
        console(
            "Invalid schedule observation; check the date, clock, IANA zone, UTC offset and output path.",
            file=sys.stderr,
        )
        return 2
    return {"supplied_observation_matches": 0, "supplied_observation_mismatch": 1}.get(str(result["status"]), 3)


if __name__ == "__main__":
    raise SystemExit(main())
