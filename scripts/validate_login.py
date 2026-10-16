#!/usr/bin/env python3
"""Validate NOTTY login against live API and phone-app observations."""

from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.app_validation import main
from scripts.login_validation import main as login_main

AUTH_FLAGS = {"--request-code", "--exchange-code"}

if __name__ == "__main__":
    if AUTH_FLAGS.intersection(sys.argv):
        raise SystemExit(login_main())
    raise SystemExit(main("login"))
