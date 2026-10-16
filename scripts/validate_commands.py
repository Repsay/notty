#!/usr/bin/env python3
"""Safely validate NOTTY litter-box settings using an existing local session.

The default is read-only. Explicit --execute plus an interactive typed
confirmation is required for any write. Motor, reset and calibration commands
are intentionally not supported here.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from scripts.probe_datapoints import load_api

SETTINGS = {
    "child-lock": ("set_key", "switch_key"),
    "dnd": ("set_dnd", "switch_dnd"),
}
STATUS_KEYS = (
    "status_id",
    "status",
    "mode",
    "switch_key",
    "switch_dnd",
    "dnd_begin_time",
    "dnd_end_time",
)


class ValidationError(Exception):
    """The requested test is unsafe or cannot be validated."""


def load_session(path: Path) -> dict[str, Any]:
    if not path.name.endswith(".private.json"):
        raise ValidationError("Use a session filename ending in .private.json")
    if path.is_symlink() or not path.is_file():
        raise ValidationError("Session file must exist and must not be a symlink")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise ValidationError("Session file permissions are too broad; use chmod 600")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("Session file is not valid JSON") from exc
    if not isinstance(data, dict) or not data.get("access_token") or not data.get("user_id"):
        raise ValidationError("Session file requires access_token and user_id")
    return data


def status(info: dict[str, Any]) -> dict[str, Any]:
    """Return only non-sensitive operational fields."""
    return {key: info.get(key) for key in STATUS_KEYS}


def state_number(value: Any) -> int | None:
    if value in (0, 1, "0", "1", False, True):
        return int(value)
    return None


def action_payload(action: str, requested: int, info: dict[str, Any]) -> dict[str, Any]:
    _, field = SETTINGS[action]
    payload: dict[str, Any] = {field: requested}
    if action == "dnd":
        begin = info.get("dnd_begin_time")
        end = info.get("dnd_end_time")
        if not isinstance(begin, str) or not isinstance(end, str):
            raise ValidationError("Cannot preserve current Do Not Disturb interval")
        if requested == 1 and begin == end:
            raise ValidationError(
                "Cannot enable Do Not Disturb with identical start/end times"
            )
        payload.update({"dnd_begin_time": begin, "dnd_end_time": end})
    return payload


async def validate(
    api: Any,
    *,
    device_id: str,
    action: str,
    value: str | None,
    execute: bool,
    ask: Any = input,
    sleep: Any = asyncio.sleep,
    interactive: bool | None = None,
) -> int:
    before = await api.litter_info(device_id)
    if not isinstance(before, dict) or not before:
        raise ValidationError("No device information received; no write performed")
    if str(before.get("user_device_id")) != device_id:
        raise ValidationError("Device ID mismatch; no write performed")

    print("BEFORE:", json.dumps(status(before), sort_keys=True))
    if action == "status":
        if value or execute:
            raise ValidationError("Status only supports read-only mode")
        return 0

    if action not in SETTINGS or value not in ("on", "off"):
        raise ValidationError("Select child-lock or dnd and specify --state on/off")
    endpoint, field = SETTINGS[action]
    requested = int(value == "on")
    current = state_number(before.get(field))
    if current is None:
        raise ValidationError(f"Current {field} is unknown; no write performed")
    payload = action_payload(action, requested, before)

    print(
        "PLAN:",
        json.dumps(
            {
                "action": action,
                "from": current,
                "to": requested,
                "api_action": endpoint,
                "settings": payload,
                "same_state": current == requested,
            },
            sort_keys=True,
        ),
    )
    if not execute:
        print("DRY RUN ONLY: no API write performed. Add --execute to opt in.")
        return 0

    if state_number(before.get("status_id")) != 1 or state_number(before.get("status")) != 0:
        raise ValidationError("Box is offline or not idle; no write performed")
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise ValidationError("Write tests require an interactive terminal")
    phrase = f"WRITE {device_id} {action} {value}"
    if ask(f"Type '{phrase}' to authorize ONE setting write: ").strip() != phrase:
        raise ValidationError("Confirmation did not match; no write performed")

    # Exactly one write. No retry, no alternate guessed payloads.
    await api.litter_action(device_id, endpoint, payload)
    print("WRITE REQUEST RETURNED: checking read-back (not proof of physical behavior)")
    for _ in range(3):
        await sleep(4)
        after = await api.litter_info(device_id)
        if isinstance(after, dict) and str(after.get("user_device_id")) == device_id:
            print("AFTER:", json.dumps(status(after), sort_keys=True))
            if state_number(after.get(field)) == requested:
                if current == requested:
                    print("SAME-STATE ACK: endpoint accepted; no state transition demonstrated")
                else:
                    print("READ-BACK CONFIRMED: setting changed; verify physically/app")
                return 0
    print("NOT CONFIRMED: API value did not match; do not repeat automatically")
    return 1


async def run(args: argparse.Namespace) -> int:
    saved = load_session(args.session_file)
    import aiohttp

    async with aiohttp.ClientSession() as session:
        api = load_api.NottyApi(
            session,
            token=saved["access_token"],
            user_id=saved["user_id"],
            email=saved.get("email"),
            region_code=saved.get("region_code", "NL"),
        )
        return await validate(
            api,
            device_id=args.device_id,
            action=args.action,
            value=args.state,
            execute=args.execute,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument("--device-id", required=True, help="Physical user_device_id")
    parser.add_argument(
        "action",
        choices=("status", "child-lock", "dnd"),
        nargs="?",
        default="status",
    )
    parser.add_argument("--state", choices=("on", "off"))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Allow one real settings write after a typed confirmation",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except (ValidationError, load_api.NottyAuthError, load_api.NottyApiError, OSError):
        # API error bodies may include private account or device information.
        print(
            "Validation stopped; no further commands were sent. Check session, "
            "device state and arguments. If a write was attempted, read state "
            "before deciding what to do next.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
