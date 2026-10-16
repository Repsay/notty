#!/usr/bin/env python3
"""Inspect the verified NOTTY timezone catalog without changing device settings.

By default, display only JSON paths, types and the number of catalog entries.
Pass --find Amsterdam to show ONLY matching public timezone records, including
their server-provided IDs. A raw capture is optional and remains local/private.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, cast

import aiohttp

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if TYPE_CHECKING:
    from custom_components.notty.api import JsonObject, JsonValue
from scripts import probe_datapoints
from scripts.console import console
from scripts.validate_commands import load_session

TIME_ZONE_CATALOG_PATH = "/entity/get_time_zones"
CATALOG_FIELDS = ("id", "display_name", "offset")
MAX_MATCHES = 10
MIN_FIND_LENGTH = 3
MAX_TIMEZONE_TEXT_LENGTH = 128
SOURCE_PET = "pet"
DEVICE_TIMEZONE_KEYS = ("time_zone_iana", "time_zone", "timezone", "time_zone_id", "timezone_id")


def catalog_entries(response: JsonValue) -> list[JsonObject]:
    """Validate the owner-observed list of timezone records.

    Returns:
        Catalog entries containing only string id, display_name and offset.
        An offset is opaque server text, not necessarily a DST-aware UTC offset.

    Raises:
        TypeError: If the response or required fields have incorrect types.
        ValueError: If a catalog entry is empty or has a duplicate ID.
    """
    if not isinstance(response, list):
        msg = "Timezone catalog must be an array"
        raise TypeError(msg)
    entries: list[JsonObject] = []
    seen_ids: set[str] = set()
    for item in response:
        if not isinstance(item, dict):
            msg = "Timezone catalog contains a non-object entry"
            raise TypeError(msg)
        entry: JsonObject = {}
        for field in CATALOG_FIELDS:
            value = item.get(field)
            if not isinstance(value, str):
                msg = "Timezone catalog entry has a missing or invalid string field"
                raise TypeError(msg)
            if not value.strip():
                msg = "Timezone catalog entry has an empty field"
                raise ValueError(msg)
            entry[field] = value.strip()
        identifier = entry["id"]
        if not isinstance(identifier, str) or identifier in seen_ids:
            msg = "Timezone catalog has a duplicate or invalid ID"
            raise ValueError(msg)
        seen_ids.add(identifier)
        entries.append(entry)
    return entries


def catalog_report(response: JsonValue, *, find: str | None = None) -> JsonObject:
    """Report schema, optionally revealing only matching public timezone entries.

    Returns:
        Value-free inventory and entry count by default; when explicitly
        requested, a bounded list of matching catalog IDs/names/offsets.

    Raises:
        ValueError: If entries are malformed or the search is too short.
    """
    entries = catalog_entries(response)
    report: JsonObject = {
        "method": "GET",
        "endpoint": TIME_ZONE_CATALOG_PATH,
        "entry_count": len(entries),
        "paths_and_types": cast("JsonObject", probe_datapoints.load_inventory(response)),
    }
    if find is not None:
        term = find.strip().casefold()
        if len(term) < MIN_FIND_LENGTH:
            msg = "Timezone search must contain at least three characters"
            raise ValueError(msg)
        matches = [
            entry for entry in entries if any(term in str(entry[field]).casefold() for field in ("id", "display_name"))
        ]
        report.update({
            "match_count": len(matches),
            "matches_truncated": len(matches) > MAX_MATCHES,
            "matches": cast("JsonValue", matches[:MAX_MATCHES]),
        })
    return report


async def collect_catalog(api: probe_datapoints.load_api.NottyApi) -> JsonValue:
    """Perform exactly one read-only catalog request.

    Returns:
        The unmodified API result, intended only for local private capture.
    """
    return await api.request("GET", TIME_ZONE_CATALOG_PATH)


def device_timezone_fields(info: JsonObject) -> JsonObject:
    """Select only public timezone-related fields, never device identifiers.

    Returns:
        A sanitized subset of known timezone attributes.
    """
    return {
        key: value
        for key in DEVICE_TIMEZONE_KEYS
        if isinstance((value := info.get(key)), str) and 0 < len(value) <= MAX_TIMEZONE_TEXT_LENGTH
    }


async def inspect_device_timezone(api: probe_datapoints.load_api.NottyApi, device_id: str) -> JsonObject:
    """Inspect timezone values on one account-owned device using reads only.

    Returns:
        A non-identifying report from the device listing and litter-box info.

    Raises:
        ValueError: If the requested device is not in the account's device list.
    """
    devices = await api.devices()
    matched = next(
        (
            device
            for device in devices
            if device.get("_notty_source") != SOURCE_PET
            and str(device.get("user_device_id") or device.get("device_id") or "") == device_id
        ),
        None,
    )
    if matched is None:
        msg = "Requested litter box does not match an account device"
        raise ValueError(msg)
    info = await api.litter_info(device_id)
    return {"device_listing": device_timezone_fields(matched), "litter_box_info": device_timezone_fields(info)}


@dataclass
class TimezoneProbeOptions:
    """Read-only timezone probe arguments."""

    session_file: Path
    capture_raw: Path | None = None
    find: str | None = None
    device_id: str | None = None


async def run(options: TimezoneProbeOptions) -> JsonObject:
    """Read a catalog with a verified local session and report schema only.

    Returns:
        Non-sensitive JSON schema summary.

    Raises:
        ValueError: If the capture path is unsafe or would overwrite a file.
        TypeError: If the saved session has malformed credentials.
    """
    if options.capture_raw and (not options.capture_raw.name.endswith(".private.json") or options.capture_raw.exists()):
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
            session, token=token, user_id=user_id, region_code=str(session_data.get("region_code") or "NL")
        )
        response = await collect_catalog(api)
        device_report = await inspect_device_timezone(api, options.device_id) if options.device_id else None
    if options.capture_raw:
        probe_datapoints.write_json(options.capture_raw, {"time_zones": response})
    report = catalog_report(response, find=options.find)
    if device_report is not None:
        report["device_timezone_fields"] = device_report
    return report


def main() -> int:
    """Read timezone metadata only, without any POST or configuration actions.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True, help="Owner-only *.private.json session")
    parser.add_argument("--capture-raw", type=Path, help="Save response locally to a new *.private.json file")
    parser.add_argument("--find", help="Print up to 10 catalog entries matching an ID or display name")
    parser.add_argument("--device-id", help="Read timezone fields from one of your listed litter boxes (read-only)")
    options = cast("TimezoneProbeOptions", parser.parse_args())
    try:
        console(json.dumps(asyncio.run(run(options)), indent=2))
    except probe_datapoints.load_api.NottyApiError, OSError, TypeError, ValueError:
        console("Read-only timezone inventory failed; no device changes were attempted.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
