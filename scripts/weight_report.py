"""Conservative analysis of private NOTTY weight captures, without HA imports."""

from __future__ import annotations

from datetime import UTC, datetime
import math
import re
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from custom_components.notty.api import JsonObject, JsonValue

WEIGHT_FIELDS = {
    "weight",
    "today_weight",
    "yesterday_weight",
    "total_weight",
    "average_weight",
    "avg_weight",
    "last_weight",
    "latest_weight",
    "body_weight",
    "weight_value",
}
UNIT_FIELDS = ("weight_unit", "weight_unit_name", "unit")
TIME_FIELDS = (
    "date",
    "time",
    "datetime",
    "timestamp",
    "measured_at",
    "weight_time",
    "weight_date",
    "utc_create",
    "utc_modified",
    "created_at",
)
STRUCTURE_FIELDS = {
    "data",
    "list",
    "rows",
    "items",
    "statistics",
    "detail",
    "weights",
    "weight_list",
    "weight_data",
    *WEIGHT_FIELDS,
}
PROFILE = "profile"
FIELD_WEIGHT = "weight"
MAX_FINDINGS = 500
MAX_DEPTH = 16
CAPTURE_VERSION = 1
FIELD_DATA = "data"
SOURCE_PATTERN = re.compile(
    r"(?:pet\[[1-9][0-9]*\]\.profile|box\[[1-9][0-9]*\]\.(?:info|pet_list|associations|pet\[[1-9][0-9]*\]\.(?:statistics|detail)))"
)


def positive_number(value: JsonValue) -> float | None:
    """Parse finite positive measurements without accepting Booleans or units.

    Returns:
        A numeric candidate, otherwise None.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except ValueError, OverflowError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def unit_evidence(row: JsonObject) -> JsonObject:
    """Keep explicit unit text separate from unverified numeric enum mappings.

    Returns:
        A safe description, never an assumed kilogram conversion.
    """
    for key in UNIT_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and value.strip().lower() in {"kg", "lb", "lbs", "g"}:
            return {"field": key, "reported": value.strip().lower(), "status": "explicit_text"}
        if type(value) is int or (isinstance(value, str) and value.isascii() and value.isdecimal()):
            return {"field": key, "reported": value, "status": "unverified_enum"}
    return {"status": "missing_or_unknown"}


def _find_weights(
    value: JsonValue, *, path: str = "$", depth: int = 0
) -> tuple[list[tuple[str, str, JsonValue, JsonObject]], bool]:
    if depth > MAX_DEPTH:
        return [], True
    result: list[tuple[str, str, JsonValue, JsonObject]] = []
    truncated = False
    children: list[tuple[str, JsonValue]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            safe_key = key if key in STRUCTURE_FIELDS else "*"
            child_path = f"{path}.{safe_key}"
            if key in WEIGHT_FIELDS and not isinstance(child, (dict, list)):
                result.append((child_path, key, child, value))
            elif isinstance(child, (dict, list)):
                children.append((child_path, child))
    elif isinstance(value, list):
        if path.rsplit(".", 1)[-1] in WEIGHT_FIELDS | {"weights", "weight_list"}:
            result.extend(
                (f"{path}[{index}]", "weight", child, {})
                for index, child in enumerate(value)
                if not isinstance(child, (dict, list))
            )
        children = [(f"{path}[{index}]", child) for index, child in enumerate(value) if isinstance(child, (dict, list))]
    for child_path, child in children:
        found, limited = _find_weights(child, path=child_path, depth=depth + 1)
        result.extend(found)
        truncated |= limited
        if len(result) >= MAX_FINDINGS:
            return result[:MAX_FINDINGS], True
    return result, truncated


def _timestamp_context(row: JsonObject, *, show_values: bool) -> JsonObject:
    context: JsonObject = {}
    for key in TIME_FIELDS:
        value = row.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            context[key] = value if show_values else type(value).__name__
    return context


def source_report(source: JsonObject, *, show_values: bool) -> JsonObject:
    """Inventory candidate fields without claiming profile weight was measured.

    Returns:
        Pseudonymous source metadata, field evidence and explicit limitations.
    """
    found, truncated = _find_weights(source.get("data"))
    fields: list[JsonValue] = []
    for path, field, value, context in found:
        entry: JsonObject = {
            "path": path,
            "field": field,
            "role": "profile_setting"
            if source.get("kind") == PROFILE and field == FIELD_WEIGHT
            else "unverified_measurement_candidate",
            "value_type": type(value).__name__,
            "positive_finite_number": positive_number(value) is not None,
            "unit": unit_evidence(context),
            "timestamp_context": _timestamp_context(context, show_values=show_values),
        }
        if show_values:
            entry["reported_value"] = value
        fields.append(entry)
    return {
        "source": source["label"],
        "kind": source["kind"],
        "response_type": type(source.get("data")).__name__,
        "fields": fields,
        "truncated": truncated,
    }


def capture_sources(capture: JsonObject) -> list[JsonObject]:
    """Validate this tool's capture schema before analysing or comparing it.

    Returns:
        Captured source objects.

    Raises:
        ValueError: If this is not a complete compatible weight-probe capture.
    """
    sources = capture.get("sources")
    if (
        type(capture.get("schema_version")) is not int
        or capture["schema_version"] != CAPTURE_VERSION
        or not isinstance(sources, list)
        or not isinstance(capture.get("errors"), list)
    ):
        msg = "Expected a version-1 weight-probe capture"
        raise ValueError(msg)
    result: list[JsonObject] = []
    seen: set[str] = set()
    for source in sources:
        if (
            not isinstance(source, dict)
            or not all(isinstance(source.get(key), str) for key in ("label", "kind", "identity"))
            or FIELD_DATA not in source
        ):
            msg = "Malformed weight-probe source"
            raise ValueError(msg)
        # Labels and kinds are generated by this tool; arbitrary capture text is not printed.
        label = source["label"]
        kind = source["kind"]
        if (
            not isinstance(label, str)
            or SOURCE_PATTERN.fullmatch(label) is None
            or not isinstance(kind, str)
            or kind not in {PROFILE, "info", "pet_list", "associations", "statistics", "detail"}
        ):
            msg = "Unknown weight-probe source label or kind"
            raise ValueError(msg)
        identity = str(source["identity"])
        if identity in seen:
            msg = "Duplicate weight-probe source identity"
            raise ValueError(msg)
        seen.add(identity)
        result.append(source)
    return result


def compare_captures(before: JsonObject, after: JsonObject) -> JsonObject:
    """Join snapshots by private stable IDs, never by potentially reordered labels.

    Returns:
        Change counts and current pseudonyms; no values or identifiers.
    """
    previous = {str(source["identity"]): source for source in capture_sources(before)}
    changes: list[JsonValue] = []
    for source in capture_sources(after):
        old = previous.pop(str(source["identity"]), None)
        if old is None:
            changes.append({"source": source["label"], "status": "new_source"})
            continue
        old_fields, _ = _find_weights(old["data"])
        new_fields, _ = _find_weights(source["data"])
        # List positions may change; this is a response comparison, not event deduplication.
        changed = [(path, field, value) for path, field, value, _ in old_fields] != [
            (path, field, value) for path, field, value, _ in new_fields
        ]
        context_changed = [
            (path, _timestamp_context(row, show_values=True), unit_evidence(row)) for path, _, _, row in old_fields
        ] != [(path, _timestamp_context(row, show_values=True), unit_evidence(row)) for path, _, _, row in new_fields]
        changes.append({
            "source": source["label"],
            "weight_response_changed": changed,
            "timestamp_or_unit_context_changed": context_changed,
        })
    return {
        "sources": changes,
        "missing_previous_sources": len(previous),
        "interpretation": "Response changes do not prove a new weigh-in; list order and aggregates can change.",
    }


def report(capture: JsonObject, *, show_values: bool = False, before: JsonObject | None = None) -> JsonObject:
    """Produce a conservative discovery report rather than a production-readiness verdict.

    Returns:
        Weight field evidence, source coverage and optional before/after differences.
    """
    sources = capture_sources(capture)
    errors = capture.get("errors")
    result: JsonObject = {
        "schema_version": CAPTURE_VERSION,
        "analysed_at": datetime.now(UTC).isoformat(),
        "sources": cast("list[JsonValue]", [source_report(source, show_values=show_values) for source in sources]),
        "failed_reads": len(errors) if isinstance(errors, list) else 0,
        "limitations": [
            "All device/pet weight fields are candidates until compared with the official app after a normal visit.",
            "Profile weight is an editable setting, not evidence of a litter-box measurement.",
            "Numeric unit codes are not converted; verify the enum against APK and app settings.",
            "Timestamps are reported as supplied; their timezone and meaning are unverified.",
            "Historical response rows are not imported into Home Assistant history.",
        ],
    }
    if before is not None:
        result["comparison"] = compare_captures(before, capture)
    return result
