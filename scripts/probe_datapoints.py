#!/usr/bin/env python3
"""Inspect NOTTY read endpoints without importing Home Assistant or running commands."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str):
    """Load standalone helpers without executing the integration's HA imports."""
    spec = importlib.util.spec_from_file_location(
        f"notty_probe_{name}", ROOT / "custom_components" / "notty" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    """Create private captures without overwriting existing files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


async def collect(api, device_ids: list[str]) -> dict:
    """Only call discovery and known read methods; never arbitrary endpoints."""
    responses = {}
    errors = []

    async def read(key, method, *args):
        try:
            result = await method(*args)
        except load_api.NottyAuthError:
            raise
        except load_api.NottyApiError:
            # Error bodies may echo credentials, account IDs, or personal data.
            errors.append({"endpoint": key, "error": "request_failed"})
            return None
        responses[key] = result
        return result

    devices = await read("devices", api.devices)
    pets = await read("pets", api.pets)
    ids = set(device_ids)
    for device in devices or []:
        if device.get("_notty_source") == "pet":
            continue
        device_id = device.get("user_device_id") or device.get("device_id") or device.get("id")
        device_type = " ".join(
            str(device.get(k, ""))
            for k in ("device_type", "type", "category", "device_name", "product_name", "model")
        ).lower()
        if device_id and ("litter" in device_type or "sand" in device_type):
            ids.add(str(device_id))
    # Labels use ordinal numbers so report paths do not expose device/pet IDs.
    for index, device_id in enumerate(sorted(ids)):
        await read(f"litter_boxes[{index}].info", api.litter_info, device_id)
        await read(f"litter_boxes[{index}].related", api.litter_related_info, device_id)
    for index, pet in enumerate(pets or []):
        pet_id = pet.get("pet_id") or pet.get("id")
        if pet_id is not None:
            await read(f"pets[{index}].related", api.pet_related_info, str(pet_id))
    return {"responses": responses, "errors": errors}


def report(capture: dict) -> dict:
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "datapoints": load_module("datapoints").inventory(capture["responses"]),
        "errors": capture.get("errors", []),
    }


async def run(args) -> int:
    # Validate paths before consuming a one-time login code or making requests.
    for path in (args.capture_raw, args.session_file):
        if path and not path.name.endswith(".private.json"):
            raise ValueError("Sensitive output filenames must end in .private.json")
    for path in (args.output, args.capture_raw):
        if path and path.exists():
            raise FileExistsError(path)
    if args.from_file:
        capture = json.loads(args.from_file.read_text())
        if "responses" not in capture:
            raise ValueError("Expected a probe capture containing 'responses'")
    else:
        import aiohttp

        saved_session = {}
        if args.session_file and args.session_file.exists():
            saved_session = json.loads(args.session_file.read_text())
            email = os.environ.get("NOTTY_EMAIL")
            if email and email.strip().casefold() != saved_session.get("email", "").casefold():
                raise ValueError("Session belongs to a different email address")
        async with aiohttp.ClientSession() as session:
            api = load_api.NottyApi(
                session,
                token=os.environ.get("NOTTY_ACCESS_TOKEN") or saved_session.get("access_token"),
                user_id=os.environ.get("NOTTY_USER_ID") or saved_session.get("user_id"),
                email=os.environ.get("NOTTY_EMAIL") or saved_session.get("email"),
                password=os.environ.get("NOTTY_PASSWORD"),
                verification_code=os.environ.get("NOTTY_VERIFICATION_CODE"),
                region_code=os.environ.get("NOTTY_REGION_CODE")
                or saved_session.get("region_code", "NL"),
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
            capture = await collect(api, args.device_id)
    result = report(capture)
    if args.capture_raw:
        write_json(args.capture_raw, capture)
    if args.output:
        write_json(args.output, result)
    else:
        print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


load_api = load_module("api")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", action="append", default=[], help="Explicit litter box ID")
    parser.add_argument("--from-file", type=Path, help="Inventory a local raw capture, offline")
    parser.add_argument("--output", type=Path, help="Save value-free datapoint report")
    parser.add_argument(
        "--capture-raw", type=Path, help="Save sensitive responses to *.private.json"
    )
    parser.add_argument(
        "--session-file",
        type=Path,
        help="Reuse or save login tokens locally in an owner-only *.private.json file",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except load_api.NottyAuthError:
        print(
            "Authentication failed. Check NOTTY credentials or obtain a fresh token.",
            file=sys.stderr,
        )
        return 2
    except load_api.NottyApiError, OSError, ValueError:
        print(
            "Probe failed. Check connectivity, input JSON, and output paths (files must be new).",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
