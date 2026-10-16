#!/usr/bin/env python3
"""Compare two value-free reports produced by probe_datapoints.py."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, cast

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.console import console

if TYPE_CHECKING:
    from custom_components.notty.api import JsonObject


def compare(before: JsonObject, after: JsonObject) -> JsonObject:
    """Compare.

    Returns:
        JsonObject: The resulting compare.

    Raises:
        TypeError: When the requested operation cannot be completed.
    """
    old, new = before["datapoints"], after["datapoints"]
    if not isinstance(old, dict) or not isinstance(new, dict):
        message = "Reports must contain datapoint objects"
        raise TypeError(message)
    return {
        "added": {key: new[key] for key in sorted(new.keys() - old.keys())},
        "removed": {key: old[key] for key in sorted(old.keys() - new.keys())},
        "type_changed": {
            key: {"before": old[key], "after": new[key]}
            for key in sorted(old.keys() & new.keys())
            if old[key] != new[key]
        },
    }


@dataclass
class CompareOptions:
    """Paths to the two probe reports."""

    before: Path
    after: Path


def main() -> int:
    """Main.

    Returns:
        int: The resulting main.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = cast("CompareOptions", parser.parse_args())
    result = compare(
        cast("JsonObject", json.loads(args.before.read_text())), cast("JsonObject", json.loads(args.after.read_text()))
    )
    console(json.dumps(result, indent=2))
    return int(any(result.values()))


if __name__ == "__main__":
    raise SystemExit(main())
