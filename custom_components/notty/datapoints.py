"""Value-free datapoint inventories shared by diagnostics and developer tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.notty.api import JsonValue


def inventory(value: JsonValue, path: str = "$", *, _fields: dict[str, set[str]] | None = None) -> dict[str, list[str]]:
    """Describe JSON paths and observed types, without retaining response values.

    Array indices are combined so snapshots can be compared across polling runs.

    Returns:
        The computed result.
    """
    fields = {} if _fields is None else _fields
    kind = (
        "null"
        if value is None
        else "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "number"
        if isinstance(value, float)
        else "string"
        if isinstance(value, str)
        else "object"
        if isinstance(value, dict)
        else "array"
        if isinstance(value, list)
        else "unknown"
    )
    fields.setdefault(path, set()).add(kind)
    if isinstance(value, dict):
        for key, item in value.items():
            inventory(item, f"{path}.{key}", _fields=fields)
    elif isinstance(value, list):
        for item in value:
            inventory(item, f"{path}[]", _fields=fields)
    return {key: sorted(kinds) for key, kinds in sorted(fields.items())}
