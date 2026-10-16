#!/usr/bin/env python3
"""Compare two value-free reports produced by probe_datapoints.py."""

import argparse
import json
from pathlib import Path


def compare(before: dict, after: dict) -> dict:
    old, new = before["datapoints"], after["datapoints"]
    return {
        "added": {key: new[key] for key in sorted(new.keys() - old.keys())},
        "removed": {key: old[key] for key in sorted(old.keys() - new.keys())},
        "type_changed": {
            key: {"before": old[key], "after": new[key]}
            for key in sorted(old.keys() & new.keys())
            if old[key] != new[key]
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    print(json.dumps(result, indent=2))
    return int(any(result.values()))


if __name__ == "__main__":
    raise SystemExit(main())
