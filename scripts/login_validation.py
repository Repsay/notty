"""Explicit NOTTY email-code request/exchange using the integration login contract."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import cast

import aiohttp

from scripts import probe_datapoints
from scripts.console import console


@dataclass
class LoginOptions:
    """Explicit one-time login operation and optional new private session path."""

    request_code: bool = False
    exchange_code: bool = False
    new_session_file: Path | None = None


async def run(options: LoginOptions) -> dict[str, str]:
    """Request a code or exchange a supplied code once, without publishing secrets.

    Returns:
        Authentication acknowledgement only; no credentials or email address.

    Raises:
        ValueError: If inputs are missing or a session could be overwritten.
    """
    email = os.environ.get("NOTTY_EMAIL")
    code = os.environ.get("NOTTY_VERIFICATION_CODE")
    if not email or options.request_code == options.exchange_code:
        msg = "Set NOTTY_EMAIL and choose one login operation"
        raise ValueError(msg)
    path = options.new_session_file
    if options.exchange_code and (not code or path is None):
        msg = "Code exchange requires NOTTY_VERIFICATION_CODE and --new-session-file"
        raise ValueError(msg)
    if path and (not path.name.endswith(".private.json") or path.exists() or path.is_symlink()):
        msg = "Use a new .private.json session path"
        raise ValueError(msg)
    async with aiohttp.ClientSession() as session:
        api = probe_datapoints.load_api.NottyApi(
            session, email=email, verification_code=code, region_code=os.environ.get("NOTTY_REGION_CODE", "NL")
        )
        if options.request_code:
            await api.request_email_code()
            return {"status": "code_request_acknowledged_check_inbox", "contract": "integration_email_code_request"}
        await api.login()
        if not api.token or not api.user_id or path is None:
            msg = "Login returned incomplete credentials"
            raise ValueError(msg)
        probe_datapoints.write_json(
            path, {"access_token": api.token, "user_id": api.user_id, "email": email, "region_code": api.region_code}
        )
        await api.pets()
    return {"status": "code_exchange_and_authenticated_read_succeeded", "contract": "integration_email_login_metadata"}


def main() -> int:
    """Run an explicit auth test; rejected/used codes are never retried.

    Returns:
        Zero on acknowledgement, two for a failed operation or local validation.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--request-code", action="store_true")
    operation.add_argument("--exchange-code", action="store_true")
    parser.add_argument("--new-session-file", type=Path)
    options = cast("LoginOptions", parser.parse_args())
    try:
        console(json.dumps(asyncio.run(run(options)), indent=2))
    except probe_datapoints.load_api.NottyApiError, OSError, ValueError:
        console("Login validation failed. Codes are not retried; credentials were not printed.", file=sys.stderr)
        return 2
    return 0
