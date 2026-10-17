"""Shared live NOTTY/phone-app comparison runner for separate feature commands."""

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

import aiohttp

from custom_components.notty.api import JsonObject, JsonValue, NottyApiError, NottyAuthError
from custom_components.notty.feature_contracts import identifier
from custom_components.notty.pet_api import MemoApi
from scripts import app_actions
from scripts.console import console
from scripts.probe_datapoints import write_json
from scripts.validate_commands import ValidationError, load_session

INFO = "/device/litter_box/get_info/{box}"
FEATURE_PATHS = {
    "login": {"pets": "/pet/list"},
    "lock": {"info": INFO},
    "dnd": {"info": INFO},
    "commands": {"info": INFO, "messages": "/device/get_message/{box}"},
    "settings": {"info": INFO},
    "reminders": {"info": INFO},
    "schedules": {"info": INFO, "plans": "/device/litter_box/plans/{box}"},
    "timezone": {"info": INFO, "plans": "/device/litter_box/plans/{box}", "catalog": "/entity/get_time_zones"},
    "alias": {"info": INFO},
    "pets": {"profile": "/pet/info/{pet}", "breeds": "/pet/breeds"},
    "associations": {"associations": "/device/get_associated_pets/{box}", "profile": "/pet/info/{pet}"},
    "notifications": {"categories": "/message/get_type_block_stats_list?message_group_id=3"},
    "memos": {"memos": "/pet/memos/{pet}"},
    "firmware": {"upgrade": "/device/check_upgrade/{box}"},
    "statistics": {
        "info": INFO,
        "daily_counts": "/device/get_daily_event_counts/{box}",
        "messages": "/device/get_message/{box}",
    },
}
FEATURE_FIELDS = {
    "lock": ("info", ("switch_key",)),
    "dnd": ("info", ("switch_dnd", "led", "dnd_begin_time", "dnd_end_time", "time_zone_iana")),
    "settings": ("info", ("mode", "auto_delay", "language")),
    "reminders": (
        "info",
        (
            "open_litter_remind",
            "default_remaining_days",
            "remaining_days",
            "open_garbagebag_remind",
            "garbage_bag_cycle_time",
            "garbage_bag_remaining_days",
        ),
    ),
    "timezone": ("info", ("time_zone_iana",)),
    "alias": ("device", ("alias",)),
    "pets": ("profile", ("name", "sex", "birthday", "breed_id", "is_sterilization", "weight", "weight_unit")),
    "firmware": ("upgrade", ("src_version", "dest_version", "task_status")),
    "statistics": ("info", ("today_clean_count",)),
}
PET_FEATURES = {"pets", "associations", "memos"}
ACCOUNT_FEATURES = {"login", "notifications"}
SOURCE_INFO = "info"
FEATURE_TIMEZONE = "timezone"
UNCHANGED = "unchanged"
DND_LOCAL_MATCH = "local_clocks_match"
FIELD_CHECKS = "checks"
MISMATCH = "mismatch"
PENDING = "pending"
MATCHED = "matches_supplied_phone_app_values"
MEMOS = "memos"
ALIAS = "alias"
LITTER_KIND = "litter_box"
LITTER_WORD = "litter"
PET_SOURCE = "pet"
LITTER_ID = 2
MAX_READBACK_ATTEMPTS = 10
MAX_READBACK_INTERVAL = 10


@dataclass
class Options:
    """Selected validation inputs and explicitly named local evidence files."""

    session_file: Path | None = None
    from_file: Path | None = None
    device_id: str | None = None
    pet_id: str | None = None
    memo_id: str | None = None
    expect: Path | None = None
    template: Path | None = None
    capture_raw: Path | None = None
    execute: Path | None = None
    roundtrip: bool = False
    output: Path | None = None
    show_values: bool = False
    readback_attempts: int = 4
    readback_interval: float = 2.0


def private_json(path: Path) -> JsonObject:
    """Read an object from an explicitly private input file.

    Returns:
        Parsed JSON object.

    Raises:
        ValueError: If the input name is invalid.
        TypeError: If the input is not an object.
    """
    if not path.name.endswith(".private.json"):
        msg = "App values, requests and captures must use .private.json filenames"
        raise ValueError(msg)
    value = cast("JsonValue", json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        msg = "Expected an object in the private input file"
        raise TypeError(msg)
    return value


def follow(data: JsonValue, path: list[JsonValue]) -> tuple[bool, JsonValue]:
    """Resolve literal keys/list indexes without evaluating code or expressions.

    Returns:
        Presence and value, distinguishing a missing field from null.
    """
    current = data
    for key in path:
        if isinstance(current, dict) and isinstance(key, str) and key in current:
            current = current[key]
            continue
        if isinstance(current, list) and type(key) is int and 0 <= key < len(current):
            current = current[key]
            continue
        return False, None
    return True, current


def app_comparison(data: JsonObject, expected: JsonObject | None, *, show_values: bool) -> JsonObject:
    """Evaluate independently entered phone-app values; pending is never success.

    Returns:
        Per-check status and a separate app-verification verdict.

    Raises:
        ValueError: If the expectation schema is malformed.
    """
    if expected is None:
        return {"status": "pending_phone_app_values", "checks": []}
    checks = expected.get("checks")
    if not isinstance(checks, list) or not checks:
        msg = "Expectations require a nonempty checks list"
        raise ValueError(msg)
    result: list[JsonValue] = []
    for index, check in enumerate(checks, 1):
        if not isinstance(check, dict) or set(check) != {"source", "path", "equals", "confirmed_from_app"}:
            msg = "Each app check requires source, path, equals and confirmed_from_app"
            raise ValueError(msg)
        source, path = check["source"], check["path"]
        if not isinstance(source, str) or source not in data or not isinstance(path, list):
            msg = "App check source or path is invalid"
            raise ValueError(msg)
        present, actual = follow(data[source], path)
        matches = present and type(actual) is type(check["equals"]) and actual == check["equals"]
        status = "pending" if check["confirmed_from_app"] is not True else "match" if matches else "mismatch"
        item: JsonObject = {"check": index, "status": status, "field_present": present}
        if show_values:
            item.update({"source": source, "path": path, "api_value": actual, "app_value": check["equals"]})
        result.append(item)
    statuses = {item["status"] for item in result if isinstance(item, dict)}
    return {
        "status": "mismatch"
        if MISMATCH in statuses
        else "pending_phone_app_values"
        if PENDING in statuses
        else "matches_supplied_phone_app_values",
        "checks": result,
    }


def template(feature: str, data: JsonObject) -> JsonObject:
    """Generate blank app observations rather than copying API values as evidence.

    Returns:
        A private editable expectation template with every check pending.
    """
    source, fields = FEATURE_FIELDS.get(feature, (next(iter(data)), ()))
    checks: list[JsonValue] = [
        {"source": source, "path": [field], "equals": None, "confirmed_from_app": False} for field in fields
    ]
    if not checks:
        checks.append({"source": source, "path": [], "equals": None, "confirmed_from_app": False})
    return {
        "checks": checks,
        "instructions": "Read the phone app, enter each exact API-typed equals value and set confirmed_from_app true. Adjust list indexes/fields from the private capture; do not copy the API response and call it independent app evidence.",
    }


async def targets(api: app_actions.ValidationApi, feature: str, options: Options) -> app_actions.Target:
    """Resolve explicit account targets; never guess among multiple cats or boxes.

    Returns:
        Physical ID, pet ID and selected discovery metadata.

    Raises:
        ValueError: If a target is ambiguous or outside the account.
    """
    pets = await api.pets()
    pet_id = str(identifier(options.pet_id)) if options.pet_id else ""
    if feature in PET_FEATURES:
        available = {str(identifier(row.get("pet_id"))) for row in pets}
        if not pet_id and len(available) == 1:
            pet_id = next(iter(available))
        if pet_id not in available:
            msg = "Select an account pet with --pet-id"
            raise ValueError(msg)
    if feature in ACCOUNT_FEATURES or feature in {"pets", "memos"}:
        return app_actions.Target("", pet_id, {})
    devices = await api.user_devices(pets)
    available_devices = {str(identifier(row.get("user_device_id"))): row for row in devices if _is_box(row)}
    device_id = str(identifier(options.device_id)) if options.device_id else ""
    if not device_id and len(available_devices) == 1:
        device_id = next(iter(available_devices))
    if device_id not in available_devices:
        msg = "Select an account physical litter box with --device-id"
        raise ValueError(msg)
    return app_actions.Target(device_id, pet_id, available_devices[device_id])


def _is_box(row: JsonObject) -> bool:
    return row.get("_notty_source") != PET_SOURCE and (
        row.get("device_type") == LITTER_KIND
        or row.get("device_id") == LITTER_ID
        or LITTER_WORD in str(row.get("product_name", "")).lower()
    )


async def collect(
    api: app_actions.ValidationApi, feature: str, target: app_actions.Target, memo_id: str | None
) -> tuple[JsonObject, list[JsonValue]]:
    """Read fixed feature routes and report optional failures without error bodies.

    Returns:
        Named responses and redacted failed-read records.

    Raises:
        NottyAuthError: If the saved session expires; stop without replay.
    """
    device = target.device
    if feature == ALIAS:
        devices = await api.user_devices(await api.pets())
        device = next((row for row in devices if str(row.get("user_device_id")) == target.box), {})
    data: JsonObject = {"device": device} if device else {}
    errors: list[JsonValue] = []
    for source, path in FEATURE_PATHS[feature].items():
        try:
            data[source] = await api.request("GET", path.format(box=target.box, pet=target.pet))
        except NottyAuthError:
            raise
        except NottyApiError:
            errors.append({"source": source, "error": "read_failed"})
    if feature == MEMOS and memo_id:
        data["detail"] = await MemoApi(api).detail(target.pet, identifier(memo_id))
    return data, errors


def _output_paths(options: Options) -> list[Path]:
    paths = [path for path in (options.capture_raw, options.output, options.template) if path]
    if options.execute and options.capture_raw:
        paths.extend([phase_path(options.capture_raw, "after"), phase_path(options.capture_raw, "restored")])
    return paths


def phase_path(path: Path, phase: str) -> Path:
    """Choose a separate private file for each write phase.

    Returns:
        A sibling filename without replacing the before capture.
    """
    return path.with_name(path.name.removesuffix(".private.json") + f".{phase}.private.json")


def validate_options(options: Options) -> None:
    """Validate private outputs before any API calls.

    Raises:
        ValueError: If modes conflict, paths exist or write evidence would be absent.
    """
    if (
        not 1 <= options.readback_attempts <= MAX_READBACK_ATTEMPTS
        or not math.isfinite(options.readback_interval)
        or not 0 <= options.readback_interval <= MAX_READBACK_INTERVAL
    ):
        msg = "Readback requires 1-10 attempts and a finite interval of 0-10 seconds"
        raise ValueError(msg)
    if (options.session_file is None) == (options.from_file is None):
        msg = "Choose exactly one saved session or offline capture"
        raise ValueError(msg)
    if options.execute and (not options.capture_raw or options.from_file):
        msg = "Executing requires live mode and a new --capture-raw before.private.json journal"
        raise ValueError(msg)
    if options.roundtrip and not options.execute:
        msg = "--roundtrip requires an explicit --execute request file"
        raise ValueError(msg)
    paths = _output_paths(options)
    if len(set(paths)) != len(paths):
        msg = "Every evidence output must use a separate file"
        raise ValueError(msg)
    for path in paths:
        if path.exists() or path.is_symlink() or not path.name.endswith(".private.json"):
            msg = "Evidence outputs must be new .private.json files"
            raise ValueError(msg)


async def _live(feature: str, options: Options) -> JsonObject:
    if options.session_file is None:
        msg = "Saved session required"
        raise ValueError(msg)
    saved = load_session(options.session_file)
    token, user = saved.get("access_token"), saved.get("user_id")
    if not isinstance(token, str) or not isinstance(user, str):
        msg = "Session credentials must be strings"
        raise TypeError(msg)
    async with aiohttp.ClientSession() as session:
        api = app_actions.ValidationApi(
            session, token=token, user_id=user, region_code=str(saved.get("region_code") or "NL")
        )
        target = await targets(api, feature, options)
        before, errors = await collect(api, feature, target, options.memo_id)
        capture: JsonObject = {
            "feature": feature,
            "captured_at": datetime.now(UTC).isoformat(),
            "data": before,
            "errors": errors,
        }
        if options.capture_raw:
            write_json(options.capture_raw, capture)
        if options.execute:
            return await execute(api, feature, target, capture, options)
        return capture


async def execute(
    api: app_actions.ValidationApi, feature: str, target: app_actions.Target, baseline: JsonObject, options: Options
) -> JsonObject:
    """Journal and execute one selected change, restoring supported settings on exit.

    Returns:
        After-readback capture and an explicit restoration result.

    Raises:
        ValueError: If preflight reads or write-request fields are invalid.
        NottyApiError: If the write/readback fails; journal uncertainty and attempt restoration.
    """
    before, errors = baseline.get("data"), baseline.get("errors")
    if not isinstance(before, dict) or errors or options.execute is None or options.capture_raw is None:
        msg = "Every baseline read must succeed before a write"
        raise ValueError(msg)
    request = private_json(options.execute)
    operation, changes = request.get("operation"), request.get("changes")
    if set(request) != {"operation", "changes"} or not isinstance(operation, str) or not isinstance(changes, dict):
        msg = "Write request requires exactly operation and changes"
        raise ValueError(msg)
    restore = app_actions.restore_request(feature, operation, changes, before) if options.roundtrip else None
    api.writes_enabled = True
    result: JsonObject = {
        "feature": feature,
        "data": {},
        "errors": [],
        "write_status": "not_attempted",
        "request": request,
    }
    result["write_status"] = "attempted"
    try:
        result["operation_result"] = await app_actions.apply(api, feature, target, operation, changes)
        result["write_status"] = "acknowledged_not_physically_verified"
        data, after_errors = await read_until_applied(api, feature, target, request, options)
        result.update({"data": data, "errors": after_errors, "captured_at": datetime.now(UTC).isoformat()})
        write_json(phase_path(options.capture_raw, "after"), result)
    except NottyApiError:
        result["write_status"] = "failed_or_uncertain_do_not_blindly_retry"
        write_json(phase_path(options.capture_raw, "after"), result)
        raise
    finally:
        if restore:
            restored_result = await restore_state(api, feature, target, restore, options)
            result["restore_status"] = restored_result["restore_status"]
            write_json(phase_path(options.capture_raw, "restored"), restored_result)
    return result


async def run(feature: str, options: Options) -> JsonObject:
    """Collect evidence and compare independently supplied phone-app observations.

    Returns:
        Redacted report; API acknowledgement and phone-app verification stay separate.

    Raises:
        ValueError: If a capture is from another feature or has malformed data.
    """
    validate_options(options)
    expected = private_json(options.expect) if options.expect else None
    capture = private_json(options.from_file) if options.from_file else await _live(feature, options)
    data, errors = capture.get("data"), capture.get("errors")
    if capture.get("feature") != feature or not isinstance(data, dict) or not isinstance(errors, list):
        msg = "Capture does not match this feature or is malformed"
        raise ValueError(msg)
    if options.template:
        write_json(options.template, template(feature, data))
    result: JsonObject = {
        "feature": feature,
        "api_reads": "partial_failure" if errors else "completed",
        "failed_reads": len(errors),
        "sources": list(data),
        "app_comparison": app_comparison(data, expected, show_values=options.show_values),
        "write_status": capture.get("write_status", "not_attempted"),
        "operation": captured_operation(feature, capture),
        "api_write_readback": write_readback(feature, capture, data),
        "restore_status": capture.get("restore_status", "not_requested"),
        "remaining": "Phone-app observations, physical effects, schedule firing/DST and firmware completion are not proved by HTTP success. Login uses an existing session; fresh code login and expiry need a separate auth test.",
    }
    if options.show_values:
        result["values"] = data
    if options.output:
        write_json(options.output, result)
    return result


def main(feature: str) -> int:
    """Run one feature's separate command.

    Returns:
        0 for supplied app values matching, 1 for failures/mismatches, 2 for errors, 3 pending app observations.
    """
    parser = argparse.ArgumentParser(
        description=f"Validate NOTTY {feature} against independently observed phone-app values. Emptying is prohibited."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session-file", type=Path)
    mode.add_argument("--from-file", type=Path)
    for name in ("device-id", "pet-id", "memo-id"):
        parser.add_argument(f"--{name}")
    for name in ("expect", "template", "capture-raw", "execute", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--readback-attempts", type=int, default=4)
    parser.add_argument("--readback-interval", type=float, default=2.0)
    parser.add_argument("--roundtrip", action="store_true")
    parser.add_argument("--show-values", action="store_true", help="Print private API values locally")
    options = cast("Options", parser.parse_args())
    try:
        result = asyncio.run(run(feature, options))
        console(json.dumps(result, indent=2, allow_nan=False))
    except NottyApiError, ValidationError, OSError, TypeError, ValueError:
        console(
            "Validation failed or a write is uncertain. Inspect private before/after/restoration evidence and the app before retrying. Emptying is prohibited.",
            file=sys.stderr,
        )
        return 2
    comparison = result["app_comparison"]
    status = comparison.get("status") if isinstance(comparison, dict) else None
    if (
        result["failed_reads"]
        or result["api_write_readback"] == MISMATCH
        or status == MISMATCH
        or result["restore_status"] not in {"not_requested", "readback_matches_baseline"}
    ):
        return 1
    return 0 if status == MATCHED else 3


async def restore_state(
    api: app_actions.ValidationApi,
    feature: str,
    target: app_actions.Target,
    restore: tuple[str, JsonObject],
    options: Options,
) -> JsonObject:
    """Restore a reversible change once, preserving evidence of failures.

    Returns:
        Original-value comparison and raw restoration evidence.
    """
    try:
        return await _restore(api, feature, target, restore, options)
    except NottyApiError:
        return {"feature": feature, "restore_status": "failed_or_uncertain_check_app_and_before_capture"}


async def _restore(
    api: app_actions.ValidationApi,
    feature: str,
    target: app_actions.Target,
    restore: tuple[str, JsonObject],
    options: Options,
) -> JsonObject:
    await app_actions.apply(api, feature, target, restore[0], restore[1])
    fresh_devices = await api.user_devices(await api.pets()) if feature == ALIAS else []
    fresh_device = next((row for row in fresh_devices if str(row.get("user_device_id")) == target.box), target.device)
    restored_target = app_actions.Target(target.box, target.pet, fresh_device)
    restored, errors = await read_until_applied(
        api, feature, restored_target, {"operation": restore[0], "changes": restore[1]}, options
    )
    restored_values = app_actions.restore_request(feature, restore[0], restore[1], restored)
    status = (
        "readback_matches_baseline" if not errors and restored_values == restore else "readback_mismatch_or_unavailable"
    )
    return {"feature": feature, "data": restored, "errors": errors, "restore_status": status}


def write_readback(feature: str, capture: JsonObject, data: JsonObject) -> str:
    """Check supported requested fields separately from independent app evidence.

    Returns:
        Match/mismatch for directly comparable writes; otherwise an explicit unknown.
    """
    request = capture.get("request")
    if not isinstance(request, dict):
        return "not_requested_or_request_not_captured"
    operation, changes = request.get("operation"), request.get("changes")
    if not isinstance(operation, str) or not isinstance(changes, dict):
        return "unreadable_request"
    if feature == FEATURE_TIMEZONE:
        return timezone_write_readback(capture, data, changes)
    try:
        actual = app_actions.restore_request(feature, operation, changes, data)
    except NottyApiError:
        return "not_interpreted_verify_in_app"
    return "match" if actual == (operation, changes) else MISMATCH


def timezone_write_readback(capture: JsonObject, data: JsonObject, changes: JsonObject) -> str:
    """Check both timezone encodings and retain partial DND-preservation failures.

    Returns:
        Match only for the requested zone and any explicitly requested preservation.
    """
    info = data.get("info")
    if not isinstance(info, dict):
        return MISMATCH
    if info.get("time_zone_iana") != changes.get("iana_time_zone") or info.get("time_zone_windows") != changes.get(
        "catalog_id"
    ):
        return MISMATCH
    outcome = capture.get("operation_result")
    if not isinstance(outcome, dict) or outcome.get("status") not in {"unchanged", "write_acknowledged_verify_in_app"}:
        return MISMATCH
    if changes.get("preserve_dnd_local_times") is True and outcome.get("status") != UNCHANGED:
        after = outcome.get("after")
        settings = after.get("settings") if isinstance(after, dict) else None
        if outcome.get("dnd_preservation") != DND_LOCAL_MATCH or not isinstance(settings, dict):
            return MISMATCH
        if any(info.get(key) != settings.get(key) for key in ("switch_dnd", "dnd_begin_time", "dnd_end_time", "led")):
            return MISMATCH
    return "match"


async def read_until_applied(
    api: app_actions.ValidationApi, feature: str, target: app_actions.Target, request: JsonObject, options: Options
) -> tuple[JsonObject, list[JsonValue]]:
    """Poll GET readback after exactly one write, without repeating the mutation.

    Returns:
        The latest data and errors, keeping a final mismatch visible to callers.
    """
    for attempt in range(options.readback_attempts):
        if attempt:
            await asyncio.sleep(options.readback_interval)
        data, errors = await collect(api, feature, target, options.memo_id)
        status = write_readback(feature, {"request": request}, data)
        if not errors and status != MISMATCH:
            return data, errors
    return data, errors


def captured_operation(feature: str, capture: JsonObject) -> str | None:
    """Expose only a recognized operation label, never private request values.

    Returns:
        The selected operation or None for reads/old/unrecognized captures.
    """
    request = capture.get("request")
    value = request.get("operation") if isinstance(request, dict) else None
    return value if isinstance(value, str) and value in app_actions.OPERATIONS.get(feature, set()) else None
