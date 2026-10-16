#!/usr/bin/env python3
"""Read NOTTY pet/profile and litter-box weight evidence; never change settings.

Default output omits weights, names, IDs and timestamp values. --show-values
prints weight/timestamp values for local comparison with the app. Save raw
captures before and after a normal visit, then compare them offline.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, cast

import aiohttp

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import probe_datapoints, weight_report
from scripts.console import console
from scripts.validate_commands import ValidationError, load_session

if TYPE_CHECKING:
    from custom_components.notty.api import JsonObject, JsonValue

SOURCE_PET = "pet"
LITTER_WORD = "litter"
SAND_WORD = "sand"
LIST_FIELDS = ("list", "data", "rows", "items")
LITTER_PRODUCT_ID = 2


def rows(value: JsonValue) -> list[JsonObject]:
    """Require a supported record-list shape instead of hiding malformed reads.

    Returns:
        Explicit object records.

    Raises:
        ValueError: If the response is absent or malformed.
    """
    if isinstance(value, dict):
        value = next((value[key] for key in LIST_FIELDS if key in value), None)
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        msg = "Unreadable NOTTY record list"
        raise ValueError(msg)
    return [row for row in value if isinstance(row, dict)]


def numeric_id(value: JsonValue) -> str:
    """Validate IDs before interpolation into a read URL.

    Returns:
        Canonical positive decimal text.

    Raises:
        ValueError: If a target has an ambiguous or unsafe identity.
    """
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return str(int(value))
    msg = "A positive numeric account target is required"
    raise ValueError(msg)


def litter_box(device: JsonObject) -> bool:
    """Recognize physical litter boxes without accepting feeder/water devices.

    Returns:
        Whether discovery explicitly identifies a litter box.
    """
    kind = " ".join(
        str(device.get(key, "")) for key in ("device_type", "type", "device_name", "product_name", "model")
    ).lower()
    return device.get("_notty_source") != SOURCE_PET and (
        LITTER_WORD in kind
        or SAND_WORD in kind
        or (type(device.get("device_id")) is int and device["device_id"] == LITTER_PRODUCT_ID)
    )


def profile_identity_matches(value: JsonValue, pet_id: str) -> bool:
    """Require profile identity before attributing its weights to a selected cat.

    Returns:
        Whether explicit response identity matches the requested account pet.
    """
    if not isinstance(value, dict):
        return False
    try:
        return numeric_id(value.get("pet_id")) == pet_id
    except ValueError:
        return False


class WeightCollector:
    """Collect fixed GET endpoints and retain failures in a private snapshot."""

    def __init__(self, api: probe_datapoints.load_api.NottyApi) -> None:
        self.api = api
        self.sources: list[JsonValue] = []
        self.errors: list[JsonValue] = []

    async def read(self, label: str, kind: str, identity: str, path: str, *, pet_id: str | None = None) -> JsonValue:
        """Read one fixed route, keeping raw error bodies out of every output.

        Returns:
            Server data or None on an explicitly recorded endpoint failure.

        Raises:
            NottyAuthError: If the saved session expires; collection stops without retry.
        """
        try:
            data = await self.api.request("GET", path)
        except probe_datapoints.load_api.NottyAuthError:
            raise
        except probe_datapoints.load_api.NottyApiError:
            self.errors.append({"source": label, "error": "request_failed"})
            return None
        if pet_id is not None and not profile_identity_matches(data, pet_id):
            self.errors.append({"source": label, "error": "profile_identity_mismatch_or_missing"})
            return None
        self.sources.append({"label": label, "kind": kind, "identity": identity, "data": data})
        return data

    async def box(self, device_id: str, label: str, pets: dict[str, str]) -> None:
        """Inspect one box, and scoped detail/history for explicitly associated account pets."""
        identity = f"box:{device_id}"
        await self.read(f"{label}.info", "info", f"{identity}:info", f"/device/litter_box/get_info/{device_id}")
        await self.read(
            f"{label}.pet_list", "pet_list", f"{identity}:pet_list", f"/device/litter_box/pet_data_list/{device_id}"
        )
        associated = await self.read(
            f"{label}.associations",
            "associations",
            f"{identity}:associations",
            f"/device/get_associated_pets/{device_id}",
        )
        if associated is None:
            return
        try:
            candidates = rows(associated)
            selected = {numeric_id(row.get("pet_id")): row for row in candidates}
        except ValueError:
            self.errors.append({"source": f"{label}.associations", "error": "malformed_list_or_identity"})
            return
        for pet_id, pet_label in pets.items():
            row = selected.get(pet_id)
            if row is None:
                continue
            state = probe_datapoints.load_api.plan_enabled(row.get("is_associated"))
            if state is None:
                self.errors.append({"source": f"{label}.{pet_label}", "error": "unknown_association_state"})
            if state is not True:
                continue
            for kind, endpoint in (("statistics", "pet_data_statistics"), ("detail", "pet_data_detail")):
                await self.read(
                    f"{label}.{pet_label}.{kind}",
                    kind,
                    f"{identity}:pet:{pet_id}:{kind}",
                    f"/device/litter_box/{endpoint}/{device_id}?pet_id={pet_id}",
                )

    async def collect(self, device_ids: list[str], pet_ids: list[str]) -> JsonObject:
        """Resolve selected targets from current account discovery before reading data.

        Returns:
            A private weight snapshot with identities preserved only for offline joining.

        Raises:
            ValueError: If a requested target is outside current account discovery.
        """
        pets = rows(await self.api.request("GET", "/pet/list"))
        account_pets = {numeric_id(pet.get("pet_id")): pet for pet in pets}
        selected_pets = {numeric_id(value) for value in pet_ids} if pet_ids else set(account_pets)
        if selected_pets - account_pets.keys():
            msg = "Requested pet is not in the current account"
            raise ValueError(msg)
        devices = await self.api.user_devices(pets)
        boxes = {numeric_id(device.get("user_device_id")): device for device in devices if litter_box(device)}
        selected_boxes = {numeric_id(value) for value in device_ids} if device_ids else set(boxes)
        if selected_boxes - boxes.keys():
            msg = "Requested physical litter box is not in the current account"
            raise ValueError(msg)
        labels = {pet_id: f"pet[{index}]" for index, pet_id in enumerate(sorted(selected_pets, key=int), 1)}
        for pet_id, label in labels.items():
            await self.read(
                f"{label}.profile", "profile", f"pet:{pet_id}:profile", f"/pet/info/{pet_id}", pet_id=pet_id
            )
        for index, device_id in enumerate(sorted(selected_boxes, key=int), 1):
            await self.box(device_id, f"box[{index}]", labels)
        if not selected_boxes or not selected_pets:
            self.errors.append({"source": "discovery", "error": "no_litter_boxes_or_pets"})
        return {
            "schema_version": 1,
            "captured_at": datetime.now(UTC).isoformat(),
            "sources": self.sources,
            "errors": self.errors,
        }


@dataclass
class WeightProbeOptions:
    """CLI inputs; every write is an explicitly named local output file."""

    session_file: Path | None = None
    from_file: Path | None = None
    compare: Path | None = None
    output: Path | None = None
    capture_raw: Path | None = None
    show_values: bool = False
    device_id: list[str] | None = None
    pet_id: list[str] | None = None


def load_capture(path: Path) -> JsonObject:
    """Load a versioned private capture for offline analysis.

    Returns:
        A validated capture object.

    Raises:
        ValueError: If the filename or JSON schema is invalid.
        TypeError: If the capture root is not an object.
    """
    if not path.name.endswith(".private.json"):
        msg = "Weight capture inputs must end in .private.json"
        raise ValueError(msg)
    value = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        msg = "Expected a weight capture object"
        raise TypeError(msg)
    weight_report.capture_sources(value)
    return value


def validate_options(options: WeightProbeOptions) -> None:
    """Check all output paths before credentials are read or network calls begin.

    Raises:
        ValueError: If input modes conflict or private/output paths are unsafe.
    """
    if (options.session_file is None) == (options.from_file is None):
        msg = "Choose exactly one of --session-file and --from-file"
        raise ValueError(msg)
    if options.from_file and (options.capture_raw or options.device_id or options.pet_id):
        msg = "Offline mode does not accept live selection or raw-capture options"
        raise ValueError(msg)
    for path in (options.capture_raw, options.output):
        if path and (path.exists() or path.is_symlink()):
            msg = "Output files must be new and must not be symlinks"
            raise ValueError(msg)
    if options.capture_raw and not options.capture_raw.name.endswith(".private.json"):
        msg = "Raw captures must end in .private.json"
        raise ValueError(msg)
    if options.show_values and options.output and not options.output.name.endswith(".private.json"):
        msg = "Reports showing weight/timestamp values must end in .private.json"
        raise ValueError(msg)
    if options.capture_raw and options.capture_raw == options.output:
        msg = "Report and raw capture must use separate paths"
        raise ValueError(msg)
    for value in (*(options.device_id or []), *(options.pet_id or [])):
        numeric_id(value)


async def run(options: WeightProbeOptions) -> JsonObject:
    """Collect live GET evidence or analyse saved data without network access.

    Returns:
        The report, including explicit failed-read counts and optional comparison.

    Raises:
        ValueError: If session credentials are malformed or input modes conflict.
    """
    validate_options(options)
    before = load_capture(options.compare) if options.compare else None
    if options.from_file:
        capture = load_capture(options.from_file)
    else:
        if options.session_file is None:
            msg = "A saved session is required for live reads"
            raise ValueError(msg)
        saved = load_session(options.session_file)
        token, user_id = saved.get("access_token"), saved.get("user_id")
        if not isinstance(token, str) or not isinstance(user_id, str):
            msg = "Saved session credentials must be strings"
            raise ValueError(msg)
        async with aiohttp.ClientSession() as session:
            api = probe_datapoints.load_api.NottyApi(
                session, token=token, user_id=user_id, region_code=str(saved.get("region_code") or "NL")
            )
            capture = await WeightCollector(api).collect(options.device_id or [], options.pet_id or [])
        if options.capture_raw:
            probe_datapoints.write_json(options.capture_raw, capture)
    result = weight_report.report(capture, show_values=options.show_values, before=before)
    if options.output:
        probe_datapoints.write_json(options.output, result)
    return result


def main() -> int:
    """Run fixed read routes only; failures never trigger a login or write retry.

    Returns:
        Zero for complete reads, one for partial reads, two for authentication/input failures.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session-file", type=Path)
    mode.add_argument("--from-file", type=Path)
    parser.add_argument("--compare", type=Path, help="Previous private weight capture; compare by private stable IDs")
    parser.add_argument("--capture-raw", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--show-values", action="store_true", help="Reveal weight/timestamp values locally; never prints names or IDs"
    )
    parser.add_argument("--device-id", action="append")
    parser.add_argument("--pet-id", action="append")
    options = cast("WeightProbeOptions", parser.parse_args())
    try:
        result = asyncio.run(run(options))
        console(json.dumps(result, indent=2, allow_nan=False))
    except probe_datapoints.load_api.NottyApiError, ValidationError, OSError, TypeError, ValueError, RecursionError:
        console(
            "Weight validation failed; check saved session and input/output files. No device changes were attempted.",
            file=sys.stderr,
        )
        return 2
    return 1 if result["failed_reads"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
