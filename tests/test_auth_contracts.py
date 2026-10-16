"""Offline authentication contracts traced from NOTTY Smart Pet 1.1.30."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notty import async_migrate_entry
from custom_components.notty.api import (
    APP_USER_AGENT,
    APP_VERSION_NUMBER,
    BASE_URL,
    NottyApi,
    NottyApiError,
    NottyAuthError,
)
from custom_components.notty.const import CONF_ACCESS_TOKEN, CONF_FIREBASE_API_KEY, CONF_PASSWORD, CONFIG_ENTRY_VERSION

EMAIL = "test@example.test"
CODE = "123456"
EXPECTED_CONTENT_TYPE = "application/json"
ANONYMOUS_USER_ID = "2"


async def test_code_request_contract() -> None:
    """Request a login code using its own APK-backed metadata."""
    api = NottyApi(MagicMock(), email=EMAIL)
    api.raw_request = AsyncMock()
    await api.request_email_code()
    api.raw_request.assert_awaited_once_with(
        "POST",
        f"{BASE_URL}/account/get_email_code",
        data={"email": EMAIL, "code_type_id": 1, "client_id": "0"},
        authenticated=False,
    )


async def test_email_login_contract_and_code_disposal() -> None:
    """Keep code-request fields out of login and discard the consumed code."""
    api = NottyApi(MagicMock(), email=EMAIL, verification_code=CODE)
    api.raw_request = AsyncMock(return_value={"access_token": "synthetic-session", "user_id": 42})
    api.devices = AsyncMock(return_value=[])
    await api.login()
    api.raw_request.assert_awaited_once_with(
        "POST",
        f"{BASE_URL}/account/login_by_email",
        data={"email": EMAIL, "code": CODE, "device_id": "1", "version_number": APP_VERSION_NUMBER},
        authenticated=False,
    )
    api.devices.assert_awaited_once()
    assert api.verification_code is None


@pytest.mark.parametrize("response", [{}, {"idToken": "google-id-credential"}, {"code": "unrelated"}])
async def test_non_notty_credentials_cannot_start_a_session(response: object) -> None:
    """An unrelated identity response must not become a NOTTY session."""
    api = NottyApi(MagicMock(), email=EMAIL, verification_code=CODE)
    api.raw_request = AsyncMock(return_value=response)
    api.devices = AsyncMock()
    with pytest.raises(NottyAuthError, match="no NOTTY access token"):
        await api.login()
    api.raw_request.assert_awaited_once()
    api.devices.assert_not_awaited()
    assert api.verification_code is None


@pytest.mark.parametrize("failure", [NottyAuthError("rejected"), NottyApiError("offline")])
async def test_login_failure_is_not_retried(failure: Exception) -> None:
    """Rejecting or losing a code exchange cannot trigger guessed endpoints."""
    api = NottyApi(MagicMock(), email=EMAIL, verification_code=CODE)
    api.raw_request = AsyncMock(side_effect=failure)
    with pytest.raises(type(failure)):
        await api.login()
    api.raw_request.assert_awaited_once()
    assert api.verification_code is None


async def test_missing_code_never_sends_credentials() -> None:
    """The client cannot attempt password or Firebase login without a code."""
    api = NottyApi(MagicMock(), email=EMAIL)
    api.raw_request = AsyncMock()
    with pytest.raises(NottyAuthError, match="fresh email verification code"):
        await api.login()
    api.raw_request.assert_not_awaited()


@pytest.mark.parametrize("version", [1, 2])
async def test_legacy_migration_preserves_session_without_submitting_secrets(hass: HomeAssistant, version: int) -> None:
    """Remove obsolete credentials while retaining existing session metadata."""
    session = {"email": EMAIL, "access_token": "synthetic-session", "user_id": "42", "region_code": "NL"}
    entry = MockConfigEntry(
        domain="notty",
        version=version,
        data={**session, CONF_PASSWORD: "obsolete", CONF_FIREBASE_API_KEY: "obsolete", "verification_code": CODE},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.notty.bootstrap.NottyApi") as constructor:
        assert await async_migrate_entry(hass, entry)
    constructor.assert_not_called()
    assert entry.version == CONFIG_ENTRY_VERSION
    assert dict(entry.data) == session


async def test_account_form_exposes_only_supported_authentication(hass: HomeAssistant) -> None:
    """The account form must not advertise unverified authentication methods."""
    result = await hass.config_entries.flow.async_init("notty", context={"source": "user"})
    fields = {str(key) for key in result["data_schema"].schema}
    assert CONF_PASSWORD not in fields
    assert CONF_FIREBASE_API_KEY not in fields


async def test_request_headers_match_established_app_client_identity() -> None:
    """Keep established wire headers when submitting a code request."""
    response = MagicMock(status=200)
    response.text = AsyncMock(return_value='{"code":0,"data":{}}')
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    session = MagicMock()
    session.request.return_value = context
    api = NottyApi(session, email=EMAIL)
    await api.request_email_code()
    headers = session.request.call_args.kwargs["headers"]
    assert headers["User-Aagent"] == APP_USER_AGENT
    assert headers["Content-Type"] == EXPECTED_CONTENT_TYPE
    assert headers["HZUID"] == ANONYMOUS_USER_ID
    assert CONF_ACCESS_TOKEN not in headers
