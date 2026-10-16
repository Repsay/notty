#!/usr/bin/env python3
"""Safely validate NOTTY litter-box settings using an existing local session.

The default is read-only. Explicit --execute plus an interactive typed
confirmation is required for any write. Motor, reset and calibration commands
are intentionally not supported here.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, TextIO, TypedDict, Unpack, cast

import aiohttp

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.console import console

if TYPE_CHECKING:
    from custom_components.notty.api import JsonObject, JsonValue, NottyApi

from scripts import probe_datapoints

POSIX_OS = "posix"
DND_ACTION = "dnd"
STATUS_ACTION = "status"
STATE_ON = "on"

load_api = probe_datapoints.load_api

SETTINGS = {"child-lock": ("set_key", "switch_key"), "dnd": ("set_dnd", "switch_dnd")}
STATUS_KEYS = ("status_id", "status", "mode", "switch_key", "switch_dnd", "led", "dnd_begin_time", "dnd_end_time")


class ValidationError(Exception):
    """The requested test is unsafe or cannot be validated."""


def load_session(path: Path) -> JsonObject:
    """Load session.

    Returns:
        JsonObject: The resulting load session.

    Raises:
        ValidationError: When the requested operation cannot be completed.
    """
    if not path.name.endswith(".private.json"):
        message = "Use a session filename ending in .private.json"
        raise ValidationError(message)
    if path.is_symlink() or not path.is_file():
        message = "Session file must exist and must not be a symlink"
        raise ValidationError(message)
    if os.name == POSIX_OS and path.stat().st_mode & 0o077:
        message = "Session file permissions are too broad; use chmod 600"
        raise ValidationError(message)
    try:
        data = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        message = "Session file is not valid JSON"
        raise ValidationError(message) from exc
    if not isinstance(data, dict) or not data.get("access_token") or not data.get("user_id"):
        message = "Session file requires access_token and user_id"
        raise ValidationError(message)
    return data


def status(info: JsonObject) -> JsonObject:
    """Return only non-sensitive operational fields."""
    return {key: info.get(key) for key in STATUS_KEYS}


def state_number(value: JsonValue) -> int | None:
    """State number.

    Returns:
        int | None: The resulting state number.
    """
    if isinstance(value, (int, float, str)) and load_api.matches_value(value, (0, 1, "0", "1", False, True)):
        return int(value)
    return None


def action_payload(action: str, requested: int, info: JsonObject, *, time_zone: str | None = None) -> JsonObject:
    """Action payload.

    Returns:
        JsonObject: The resulting action payload.

    Raises:
        ValidationError: When the requested operation cannot be completed.
    """
    if action == DND_ACTION:
        try:
            return load_api.dnd_payload(info, time_zone=time_zone, switch_dnd=requested)
        except load_api.NottyApiError as exc:
            raise ValidationError(str(exc)) from exc
    return {"switch": requested}


class ValidationHooks(TypedDict, total=False):
    """Inject console confirmation and delay functions for offline tests."""

    ask: Callable[[str], str]
    sleep: Callable[[float], Awaitable[None]]
    interactive: bool | None
    time_zone: str | None


@dataclass
class SettingPlan:
    """One setting write and the state used to validate it."""

    device_id: str
    action: str
    state: str
    endpoint: str
    field: str
    requested: int
    current: int
    payload: JsonObject


def _setting_plan(
    device_id: str, action: str, value: str | None, before: JsonObject, *, time_zone: str | None = None
) -> SettingPlan:
    if action not in SETTINGS or not load_api.matches_value(value, ("on", "off")):
        message = "Select child-lock or dnd and specify --state on/off"
        raise ValidationError(message)
    endpoint, field = SETTINGS[action]
    requested = int(value == STATE_ON)
    current = state_number(before.get(field))
    if current is None:
        message = f"Current {field} is unknown; no write performed"
        raise ValidationError(message)
    return SettingPlan(
        device_id, action, str(value), endpoint, field, requested, current, action_payload(action, requested, before, time_zone=time_zone)
    )


def _confirm_write(plan: SettingPlan, before: JsonObject, hooks: ValidationHooks) -> None:
    if state_number(before.get("status_id")) != 1 or state_number(before.get("status")) != 0:
        message = "Box is offline or not idle; no write performed"
        raise ValidationError(message)
    interactive = hooks.get("interactive")
    if interactive is None:
        interactive = cast("TextIO", sys.stdin).isatty()
    if not interactive:
        message = "Write tests require an interactive terminal"
        raise ValidationError(message)
    phrase = f"WRITE {plan.device_id} {plan.action} {plan.state}"
    ask = hooks.get("ask", input)
    if ask(f"Type '{phrase}' to authorize ONE setting write: ").strip() != phrase:
        message = "Confirmation did not match; no write performed"
        raise ValidationError(message)


async def _read_back(
    api: NottyApi, plan: SettingPlan, before: JsonObject, sleep: Callable[[float], Awaitable[None]]
) -> int:
    for _ in range(3):
        await sleep(4)
        after = await api.litter_info(plan.device_id)
        if isinstance(after, dict) and str(after.get("user_device_id")) == plan.device_id:
            console("AFTER:", json.dumps(status(after), sort_keys=True))
            if state_number(after.get(plan.field)) == plan.requested:
                if plan.action == DND_ACTION and any(
                    after.get(key) != before.get(key) for key in ("dnd_begin_time", "dnd_end_time", "led")
                ):
                    console("DND SCHEDULE CHANGED: readback differs; do not retry the write automatically")
                    return 1
                if plan.current == plan.requested:
                    console("SAME-STATE ACK: endpoint accepted; no state transition demonstrated")
                else:
                    console("READ-BACK CONFIRMED: setting changed; verify physically/app")
                return 0
    console("NOT CONFIRMED: API value did not match; do not repeat automatically")
    return 1


async def validate(
    api: NottyApi,
    *,
    device_id: str,
    action: str,
    value: str | None,
    execute: bool,
    **hooks: Unpack[ValidationHooks]
) -> int:
    """Validate one selected setting or print a read-only plan.

    Returns:
        Zero for successful readback or a dry run, one if readback fails.

    Raises:
        ValidationError: When the request cannot be validated safely.
    """
    before = await api.litter_info(device_id)
    if not isinstance(before, dict) or not before:
        message = "No device information received; no write performed"
        raise ValidationError(message)
    if str(before.get("user_device_id")) != device_id:
        message = "Device ID mismatch; no write performed"
        raise ValidationError(message)
    console("BEFORE:", json.dumps(status(before), sort_keys=True))
    if action == STATUS_ACTION:
        if value or execute:
            message = "Status only supports read-only mode"
            raise ValidationError(message)
        return 0
    plan = _setting_plan(device_id, action, value, before, time_zone=hooks.get("time_zone"))
    printable: JsonObject = {
        "action": action,
        "from": plan.current,
        "to": plan.requested,
        "api_action": plan.endpoint,
        "settings": plan.payload,
        "same_state": plan.current == plan.requested,
    }
    console("PLAN:", json.dumps(printable, sort_keys=True))
    if not execute:
        console("DRY RUN ONLY: no API write performed. Add --execute to opt in.")
        return 0
    _confirm_write(plan, before, hooks)
    # Exactly one write; confirmation does not authorize retries or alternate payloads.
    await api.litter_action(device_id, plan.endpoint, plan.payload)
    console("WRITE REQUEST RETURNED: checking read-back (not proof of physical behavior)")
    return await _read_back(api, plan, before, hooks.get("sleep", asyncio.sleep))


async def run(args: ValidationOptions) -> int:
    """Run.

    Returns:
        int: The resulting run.
    """
    saved = load_session(args.session_file)
    saved_strings = {key: value for key, value in saved.items() if isinstance(value, str)}

    async with aiohttp.ClientSession() as session:
        api = load_api.NottyApi(
            session,
            token=saved_strings["access_token"],
            user_id=saved_strings["user_id"],
            email=saved_strings.get("email"),
            region_code=saved_strings.get("region_code", "NL"),
        )
        return await validate(
            api,
            device_id=args.device_id,
            action=args.action,
            value=args.state,
            execute=args.execute,
            time_zone=args.time_zone,
        )


@dataclass
class ValidationOptions:
    """Arguments for a single explicitly selected setting validation."""

    session_file: Path
    device_id: str
    action: str
    state: str | None = None
    execute: bool = False
    time_zone: str | None = None


def main() -> int:
    """Main.

    Returns:
        int: The resulting main.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-file", type=Path, required=True)
    parser.add_argument("--device-id", required=True, help="Physical user_device_id")
    parser.add_argument("action", choices=("status", "child-lock", "dnd"), nargs="?", default="status")
    parser.add_argument("--state", choices=("on", "off"))
    parser.add_argument(
        "--time-zone", help="Fallback IANA timezone only when device does not report time_zone_iana"
    )
    parser.add_argument(
        "--execute", action="store_true", help="Allow one real settings write after a typed confirmation"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(run(cast("ValidationOptions", args)))
    except ValidationError, load_api.NottyAuthError, load_api.NottyApiError, OSError:
        # API error bodies may include private account or device information.
        console(
            "Validation stopped; no further commands were sent. Check session, "
            "device state and arguments. If a write was attempted, read state "
            "before deciding what to do next.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
