#!/usr/bin/env python3
"""Audit open-work validation coverage and summarize private reports without their values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, cast

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.console import console

if TYPE_CHECKING:
    from custom_components.notty.api import JsonObject, JsonValue

CASES = {
    11: ("lock", "validate_lock.py"),
    12: ("dnd", "validate_dnd.py"),
    14: ("login", "validate_login.py"),
    15: ("commands", "validate_cleaning.py"),
    16: ("settings", "validate_settings.py"),
    17: ("schedules", "validate_schedules.py"),
    19: ("settings", "validate_settings.py"),
    20: ("alias", "validate_alias.py"),
    21: ("timezone", "validate_timezone.py"),
    22: ("firmware", "validate_firmware.py"),
    23: ("associations", "validate_associations.py"),
    24: ("notifications", "validate_notifications.py"),
    25: ("memos", "validate_memos.py"),
    26: ("statistics", "validate_statistics.py"),
    41: ("weight", "probe_weights.py"),
    42: ("acceptance", "validation_status.py"),
}
CASE_OPERATIONS = {16: "set_auto_delay", 19: "set_mode"}
APP_MATCH = "matches_supplied_phone_app_values"
API_MATCH = "match"
API_MISMATCH = "mismatch"
RESTORED = "readback_matches_baseline"
READS_COMPLETE = "completed"


def summaries(directory: Path | None) -> tuple[dict[str, list[JsonObject]], int]:
    """Load only feature report fields used as evidence, never echoing private values.

    Returns:
        Known feature reports and unreadable-file count.
    """
    results: dict[str, list[JsonObject]] = {}
    failures = 0
    if directory is None:
        return results, failures
    known = {feature for feature, _ in CASES.values()}
    for path in directory.rglob("*.report.private.json"):
        try:
            value = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
        except OSError, ValueError:
            failures += 1
            continue
        if isinstance(value, dict):
            feature = value.get("feature")
            if isinstance(feature, str) and feature in known:
                results.setdefault(feature, []).append(value)
    return results, failures


def audit(directory: Path | None = None) -> JsonObject:
    """Separate tool coverage, live API evidence and independently supplied app evidence.

    Returns:
        A value-free issue-by-issue summary; script existence does not imply validation passed.
    """
    reports, errors = summaries(directory)
    root = Path(__file__).resolve().parent
    cases: list[JsonValue] = []
    missing = 0
    for issue, (feature, script) in CASES.items():
        exists = (root / script).is_file()
        missing += not exists
        evidence = reports.get(feature, [])
        writes = [
            row for row in evidence if issue not in CASE_OPERATIONS or row.get("operation") == CASE_OPERATIONS[issue]
        ]
        app_matches = 0
        for row in evidence:
            comparison = row.get("app_comparison")
            if isinstance(comparison, dict) and comparison.get("status") == APP_MATCH:
                app_matches += 1
        cases.append({
            "issue": issue,
            "feature": feature,
            "script": script,
            "script_available": exists,
            "api_read_reports": sum(row.get("api_reads") == READS_COMPLETE for row in evidence),
            "write_readback_matches": sum(row.get("api_write_readback") == API_MATCH for row in writes),
            "write_readback_mismatches": sum(row.get("api_write_readback") == API_MISMATCH for row in writes),
            "restoration_matches": sum(row.get("restore_status") == RESTORED for row in writes),
            "reports_matching_supplied_app_values": app_matches,
            "acceptance": "review_required_not_inferred_from_script_presence",
        })
    return {
        "cases": cases,
        "missing_scripts": missing,
        "unreadable_reports": errors,
        "deferred_issues": [27, 28],
        "notes": "Reports may include older failures and newer successes. App matches cover only supplied fields. Physical effects, DST firing, firmware completion and measured-weight freshness need their own evidence.",
    }


def main() -> int:
    """Print coverage without running a probe, changing settings or closing issues.

    Returns:
        One for missing scripts/unreadable reports, zero for complete tool coverage.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path)
    options = parser.parse_args()
    directory = cast("Path | None", options.evidence_dir)
    result = audit(directory)
    console(json.dumps(result, indent=2))
    return int(bool(result["missing_scripts"] or result["unreadable_reports"]))


if __name__ == "__main__":
    raise SystemExit(main())
