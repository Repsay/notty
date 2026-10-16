#!/usr/bin/env python3
"""Validate NOTTY timezone against live API and phone-app observations."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.app_validation import main

if __name__ == "__main__":
    raise SystemExit(main("timezone"))
