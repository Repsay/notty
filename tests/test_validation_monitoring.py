"""Firmware observations and evidence audits never substitute HTTP success for acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.notty.api import JsonValue
from scripts import monitor_firmware, validation_status
from scripts.probe_datapoints import write_json

PENDING = "pending_or_unknown"
NO_OFFER = "no_offered_update"
TARGET = "1.2.3"
CONFIRMED = "installed_version_confirmed"
FAILED = "reported_failure"
METHOD_GET = "GET"
PRIVATE_MODE = 0o600
LOCK_ISSUE = 11
PRIVATE_MARKER = "private@example.test"


@pytest.mark.parametrize(
    ("metadata", "target", "expected"),
    [
        ({"src_version": "1.0", "dest_version": TARGET, "task_status": "SUCCEEDED"}, TARGET, PENDING),
        ({"src_version": TARGET, "dest_version": "", "task_status": ""}, TARGET, CONFIRMED),
        ({"src_version": "1.0", "dest_version": "", "task_status": ""}, None, NO_OFFER),
        ({"src_version": "1.0", "dest_version": None}, None, PENDING),
        ({"src_version": "1.0", "dest_version": TARGET, "task_status": "FAILED"}, TARGET, FAILED),
        ({"src_version": "1.0", "dest_version": "other", "task_status": "FAILED"}, TARGET, PENDING),
        ({"src_version": "", "dest_version": ""}, None, "metadata_unavailable"),
    ],
)
def test_firmware_completion_requires_actual_installed_version(
    metadata: JsonValue, target: str | None, expected: str
) -> None:
    """A stale failure or success string cannot establish this target's outcome."""
    assert monitor_firmware.classify(metadata, target) == expected


async def test_monitor_only_reads_and_stops_when_installed(tmp_path: Path) -> None:
    """A target can be continued after restarting the script without installing it again."""
    session = tmp_path / "session.private.json"
    write_json(session, {"access_token": "test-token", "user_id": "test-user"})
    api = MagicMock(
        request=AsyncMock(
            side_effect=[{"src_version": "1.0", "dest_version": TARGET}, {"src_version": TARGET, "dest_version": ""}]
        )
    )
    options = monitor_firmware.MonitorOptions(session, "123", tmp_path / "monitor", target_version=TARGET, interval=0)
    with (
        patch.object(monitor_firmware, "owned_litter", AsyncMock()),
        patch.object(monitor_firmware, "ValidationApi", return_value=api),
    ):
        result = await monitor_firmware.run(options)
    assert result["status"] == CONFIRMED
    assert result["installation_attempted"] is False
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)
    assert (options.output_dir / "summary.private.json").stat().st_mode & 0o777 == PRIVATE_MODE


def test_evidence_audit_reports_coverage_without_private_values_or_automatic_acceptance(tmp_path: Path) -> None:
    """Stale failures and pending app observations remain visible alongside successes."""
    write_json(
        tmp_path / "lock.report.private.json",
        {
            "feature": "lock",
            "api_reads": "completed",
            "api_write_readback": "mismatch",
            "restore_status": "readback_matches_baseline",
            "values": {"email": "private@example.test"},
        },
    )
    report = validation_status.audit(tmp_path)
    assert report["missing_scripts"] == 0
    lock = next(row for row in report["cases"] if row["issue"] == LOCK_ISSUE)
    assert lock["write_readback_mismatches"] == 1
    assert lock["reports_matching_supplied_app_values"] == 0
    assert PRIVATE_MARKER not in json.dumps(report)
