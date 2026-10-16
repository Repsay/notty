#!/usr/bin/env python3
"""Read NOTTY's timezone catalog schema without changing device settings.

The GET method/path are APK-inferred and still need owner verification.
The default output lists only JSON paths and types, never response values.
Optionally save raw data to a private file for local contract investigation.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import cast

import aiohttp

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.notty.api import JsonObject, JsonValue
from scripts import probe_datapoints
from scripts.console import console
from scripts.validate_commands import load_session

TIME_ZONE_CATALOG_PATH = "/entity/get_time_zones"


def catalog_report(response: JsonValue) -> JsonObject:
    """Summarize structure only; never emit remote account or device values.

    Returns:
        A value-free JSON path/type inventory for the server response.
    """
    return {
        "method": "GET",
        "endpoint": TIME_ZONE_CATALOG_PATH,
        "paths_and_types": probe_datapoints.load_inventory(response),
    }


async def collect_catalog(api: probe_datapoints.load_api.NottyApi) -> JsonValue:
    """Perform exactly one read-only catalog request.

    Returns:
        The unmodified API result, intended only for local private capture.
    """
    return await api.request("GET", TIME_ZONE_CATALOG_PATH)


@dataclass
class TimezoneProbeOptions:
    """Read-only timezone probe arguments."""

    session_file: Path
    capture_raw: Path | None = None


async def run(options: TimezoneProbeOptions) -> JsonObject:
    """Read a catalog with a verified local session and report schema only.

    Returns:
        Non-sensitive JSON schema summary.

    Raises:
        ValueError: If the capture path is unsafe or would overwrite a file.
    """
    if options.capture_raw and (
        not options.capture_raw.name.endswith(".private.json") or options.capture_raw.exists()
    ):
        msg = "Raw capture must be a new file ending in .private.json"
        raise ValueError(msg)
    session_data = load_session(options.session_file)
    token = session_data["access_token"]
    user_id = session_data["user_id"]
    if not isinstance(token, str) or not isinstance(user_id, str):
        msg = "Session credentials must be strings"
        raise TypeError(msg)
    async with aiohttp.ClientSession() as session:
        api = probe_datapoints.load_api.NottyApi(
            session,
            token=token,
            user_id=user_id,
            region_code=str(session_data.get("region_code") or "NL"),
        )
        response = await collect_catalog(api)
    if options.capture_raw:
        probe_datapoints.write_json(options.capture_raw, {"time_zones": response})
    return catalog_report(response)


def main() -> int:
    """Read timezone metadata only, without any POST or configuration actions.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True, help="Owner-only *.private.json session")
    parser.add_argument("--capture-raw", type=Path, help="Save response locally to a new *.private.json file")
    options = cast("TimezoneProbeOptions", parser.parse_args())
    try:
        console(json.dumps(asyncio.run(run(options)), indent=2))
    except (probe_datapoints.load_api.NottyApiError, OSError, TypeError, ValueError):
        console("Read-only timezone inventory failed; no device changes were attempted.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
