#!/usr/bin/env python3
"""Inspect NOTTY read endpoints without importing Home Assistant or running commands."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import TYPE_CHECKING, cast

import aiohttp

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.console import console

SOURCE_PET = "pet"
LITTER_DEVICE_WORD = "litter"
SAND_DEVICE_WORD = "sand"
FIELD_RESPONSES = "responses"

if TYPE_CHECKING:
    from custom_components.notty import api as load_api
    from custom_components.notty.api import JsonObject, JsonValue, NottyApi

__all__ = ["load_api"]

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str) -> ModuleType:
    """Load standalone helpers without executing the integration's HA imports.

    Returns:
        The computed result.

    Raises:
        ImportError: When the requested operation cannot be completed.
    """
    spec = importlib.util.spec_from_file_location(
        f"notty_probe_{name}", ROOT / "custom_components" / "notty" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: JsonObject) -> None:
    """Create private captures without overwriting existing files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


async def collect(api: NottyApi, device_ids: list[str]) -> JsonObject:
    """Only call discovery and known read methods; never arbitrary endpoints.

    Returns:
        The computed result.
    """
    responses: JsonObject = {}
    errors: list[JsonValue] = []

    async def read[T](key: str, request: Awaitable[T]) -> T | None:
        """Read.

        Returns:
            T | None: The resulting read.
        """
        try:
            result = await request
        except load_api.NottyAuthError:
            raise
        except load_api.NottyApiError:
            # Error bodies may echo credentials, account IDs, or personal data.
            errors.append({"endpoint": key, "error": "request_failed"})
            return None
        responses[key] = cast("JsonValue", result)
        return result

    devices = await read("devices", api.devices())
    pets = await read("pets", api.pets())
    ids = set(device_ids)
    for device in devices or []:
        if device.get("_notty_source") == SOURCE_PET:
            continue
        device_id = device.get("user_device_id") or device.get("device_id") or device.get("id")
        device_type = " ".join(
            str(device.get(k, "")) for k in ("device_type", "type", "category", "device_name", "product_name", "model")
        ).lower()
        if device_id and (LITTER_DEVICE_WORD in device_type or SAND_DEVICE_WORD in device_type):
            ids.add(str(device_id))
    # Labels use ordinal numbers so report paths do not expose device/pet IDs.
    for index, device_id in enumerate(sorted(ids)):
        await read(f"litter_boxes[{index}].info", api.litter_info(device_id))
        await read(f"litter_boxes[{index}].related", api.litter_related_info(device_id))
    for index, pet in enumerate(pets or []):
        pet_id = pet.get("pet_id") or pet.get("id")
        if pet_id is not None:
            await read(f"pets[{index}].related", api.pet_related_info(str(pet_id)))
    return {"responses": responses, "errors": errors}


def report(capture: JsonObject) -> JsonObject:
    """Report.

    Returns:
        JsonObject: The resulting report.
    """
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "datapoints": {key: list(kinds) for key, kinds in load_inventory(capture["responses"]).items()},
        "errors": capture.get("errors", []),
    }


def _validate_probe_paths(args: ProbeOptions) -> None:
    for path in (args.capture_raw, args.session_file):
        if path and not path.name.endswith(".private.json"):
            message = "Sensitive output filenames must end in .private.json"
            raise ValueError(message)
    for path in (args.output, args.capture_raw):
        if path and path.exists():
            raise FileExistsError(path)


async def run(args: ProbeOptions) -> int:
    # Validate paths before consuming a one-time login code or making requests.
    """Run.

    Returns:
        int: The resulting run.

    Raises:
        ValueError: When the requested operation cannot be completed.
    """
    _validate_probe_paths(args)
    if args.from_file:
        capture = cast("JsonObject", json.loads(args.from_file.read_text()))
        if FIELD_RESPONSES not in capture:
            message = "Expected a probe capture containing 'responses'"
            raise ValueError(message)
    else:
        saved_session: dict[str, str] = {}
        if args.session_file and args.session_file.exists():
            saved_session = cast("dict[str, str]", json.loads(args.session_file.read_text()))
            email = os.environ.get("NOTTY_EMAIL")
            if email and email.strip().casefold() != saved_session.get("email", "").casefold():
                message = "Session belongs to a different email address"
                raise ValueError(message)
        async with aiohttp.ClientSession() as session:
            api = load_api.NottyApi(
                session,
                token=os.environ.get("NOTTY_ACCESS_TOKEN") or saved_session.get("access_token"),
                user_id=os.environ.get("NOTTY_USER_ID") or saved_session.get("user_id"),
                email=os.environ.get("NOTTY_EMAIL") or saved_session.get("email"),
                verification_code=os.environ.get("NOTTY_VERIFICATION_CODE"),
                region_code=os.environ.get("NOTTY_REGION_CODE") or saved_session.get("region_code", "NL"),
            )
            if not api.token:
                await api.login()
            if args.session_file and not args.session_file.exists():
                # Save the established session before probing, so a failed read
                # does not require another one-time email code.
                write_json(
                    args.session_file,
                    {
                        "access_token": api.token,
                        "user_id": api.user_id,
                        "email": api.email,
                        "region_code": api.region_code,
                    },
                )
            capture = await collect(api, args.device_id or [])
    result = report(capture)
    if args.capture_raw:
        write_json(args.capture_raw, capture)
    if args.output:
        write_json(args.output, result)
    else:
        console(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if not TYPE_CHECKING:
    load_api = load_module("api")

load_inventory = cast("Callable[[JsonValue], dict[str, list[str]]]", load_module("datapoints").inventory)


@dataclass
class ProbeOptions:
    """Validated command-line options for a read-only probe."""

    device_id: list[str] | None
    from_file: Path | None = None
    output: Path | None = None
    capture_raw: Path | None = None
    session_file: Path | None = None


def main() -> int:
    """Main.

    Returns:
        int: The resulting main.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", action="append", default=None, help="Explicit litter box ID")
    parser.add_argument("--from-file", type=Path, help="Inventory a local raw capture, offline")
    parser.add_argument("--output", type=Path, help="Save value-free datapoint report")
    parser.add_argument("--capture-raw", type=Path, help="Save sensitive responses to *.private.json")
    parser.add_argument(
        "--session-file", type=Path, help="Reuse or save login tokens locally in an owner-only *.private.json file"
    )
    args = cast("ProbeOptions", parser.parse_args())
    if args.device_id is None:
        args.device_id = []
    try:
        return asyncio.run(run(args))
    except load_api.NottyAuthError:
        console("Authentication failed. Check NOTTY credentials or obtain a fresh token.", file=sys.stderr)
        return 2
    except load_api.NottyApiError, OSError, ValueError:
        console("Probe failed. Check connectivity, input JSON, and output paths (files must be new).", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
