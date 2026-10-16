#!/usr/bin/env python3
"""Observe a NOTTY firmware update with bounded read-only polling and private evidence.

Run during an update started in the app or with validate_firmware.py. This tool
never installs firmware. Installed-version readback is the completion criterion.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import sys
from typing import cast

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from custom_components.notty.api import JsonObject, JsonValue, NottyApiError
from custom_components.notty.device_features import owned_litter
from custom_components.notty.feature_contracts import identifier
from scripts.app_actions import ValidationApi
from scripts.console import console
from scripts.probe_datapoints import write_json
from scripts.validate_commands import ValidationError, load_session

MAX_SAMPLES = 120
MAX_INTERVAL = 60
SUCCEEDED = "installed_version_confirmed"
FAILED = "reported_failure"
NO_OFFER = "no_offered_update"


def classify(metadata: JsonValue, target: str | None) -> str:
    """Never infer installation from an acknowledgement or a success status alone.

    Returns:
        Conservative lifecycle status based on the selected target and current version.
    """
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("src_version"), str)
        or not metadata["src_version"]
    ):
        return "metadata_unavailable"
    if target and metadata["src_version"] == target:
        return SUCCEEDED
    status = metadata.get("task_status")
    if (
        target
        and metadata.get("dest_version") == target
        and isinstance(status, str)
        and status in {"FAILED", "CANCELED"}
    ):
        return FAILED
    destination = metadata.get("dest_version")
    if not target and isinstance(destination, str) and not destination:
        return NO_OFFER
    return "pending_or_unknown"


@dataclass
class MonitorOptions:
    """A selected device, optional persisted target, and bounded observation window."""

    session_file: Path
    device_id: str
    output_dir: Path
    target_version: str | None = None
    samples: int = 6
    interval: float = 10


async def run(options: MonitorOptions) -> JsonObject:
    """Read the selected device once per sample and save evidence without write calls.

    Returns:
        Completion/failure/pending status and sample count; no fabricated percentage.

    Raises:
        ValueError: If bounds, paths or target version are invalid.
        TypeError: If session credentials are malformed.
    """
    device_id = str(identifier(options.device_id))
    if options.target_version is not None and (
        not options.target_version.strip() or not options.target_version.isprintable()
    ):
        msg = "Target version must be nonempty printable text"
        raise ValueError(msg)
    if (
        not 1 <= options.samples <= MAX_SAMPLES
        or not math.isfinite(options.interval)
        or not 0 <= options.interval <= MAX_INTERVAL
    ):
        msg = "Use 1-120 samples and a finite 0-60 second interval"
        raise ValueError(msg)
    if options.output_dir.exists() or options.output_dir.is_symlink():
        msg = "Choose a new private output directory"
        raise ValueError(msg)
    saved = load_session(options.session_file)
    token, user = saved.get("access_token"), saved.get("user_id")
    if not isinstance(token, str) or not isinstance(user, str):
        msg = "Session credentials must be strings"
        raise TypeError(msg)
    options.output_dir.mkdir(mode=0o700, parents=True)
    target = options.target_version
    status = "pending_or_unknown"
    async with aiohttp.ClientSession() as session:
        api = ValidationApi(session, token=token, user_id=user, region_code=str(saved.get("region_code") or "NL"))
        await owned_litter(api, device_id)
        for index in range(options.samples):
            if index:
                await asyncio.sleep(options.interval)
            metadata = await api.request("GET", f"/device/check_upgrade/{device_id}")
            if target is None and isinstance(metadata, dict):
                offered = metadata.get("dest_version")
                if isinstance(offered, str) and offered.strip():
                    target = offered
            status = classify(metadata, target)
            write_json(
                options.output_dir / f"sample-{index + 1:03}.private.json",
                {
                    "captured_at": datetime.now(UTC).isoformat(),
                    "target_version": target,
                    "metadata": metadata,
                    "status": status,
                },
            )
            if status in {SUCCEEDED, FAILED, NO_OFFER}:
                break
    result: JsonObject = {
        "status": status,
        "samples": index + 1,
        "target_version": target,
        "progress_percentage": None,
        "installation_attempted": False,
    }
    write_json(options.output_dir / "summary.private.json", result)
    return result


def main() -> int:
    """Observe firmware only; reuse --target-version when continuing after a restart.

    Returns:
        Zero for confirmed installed/no offer, one for failure, two for errors, three pending.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-version")
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--interval", type=float, default=10)
    options = cast("MonitorOptions", parser.parse_args())
    try:
        result = asyncio.run(run(options))
        console(json.dumps(result, indent=2))
    except NottyApiError, ValidationError, OSError, ValueError, TypeError:
        console("Firmware observation failed; no installation was attempted.", file=sys.stderr)
        return 2
    if result["status"] == FAILED:
        return 1
    return 0 if result["status"] in {SUCCEEDED, NO_OFFER} else 3


if __name__ == "__main__":
    raise SystemExit(main())
