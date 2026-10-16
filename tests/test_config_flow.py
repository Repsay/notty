from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notty.api import NottyApiError, NottyAuthError
from custom_components.notty.const import CONF_PASSWORD

EXPECTED_TEST_EXAMPLE_TEST = "test@example.test"
EXPECTED_TEST_CREDENTIAL = "test-token"
STEP_CODE = "code"
EXPECTED_VERIFICATION_CODE = "verification_code"
EXPECTED_ALREADY_CONFIGURED = "already_configured"
EXPECTED_REAUTH_SUCCESSFUL = "reauth_successful"
EXPECTED_WRONG_ACCOUNT = "wrong_account"
EXPECTED_PASSWORD_FIELD = CONF_PASSWORD


async def start(hass: HomeAssistant, data: dict[str, object]) -> ConfigFlowResult:
    """Start.

    Returns:
        ConfigFlowResult: The resulting start.
    """
    return await hass.config_entries.flow.async_init("notty", context={"source": config_entries.SOURCE_USER}, data=data)


async def test_email_login_ignores_legacy_password(hass: HomeAssistant, api_mock: MagicMock) -> None:
    """New entries use email codes even if old callers supply password data."""
    result = await start(hass, {"email": "Test@example.test", "password": "pw"})
    assert result["step_id"] == STEP_CODE
    api_mock.login.assert_not_awaited()
    api_mock.request_email_code.assert_awaited_once()
    with patch("custom_components.notty.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"verification_code": "123456"})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == EXPECTED_TEST_EXAMPLE_TEST
    assert result["data"]["access_token"] == EXPECTED_TEST_CREDENTIAL


async def test_email_code_login_does_not_store_code(hass: HomeAssistant, api_mock: MagicMock) -> None:
    """Verify email code login does not store code."""
    result = await start(hass, {"email": "test@example.test"})
    assert result["step_id"] == STEP_CODE
    api_mock.request_email_code.assert_awaited_once()
    with patch("custom_components.notty.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"verification_code": "123456"})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert EXPECTED_VERIFICATION_CODE not in result["data"]


async def test_invalid_auth_returns_form(hass: HomeAssistant, api_mock: MagicMock) -> None:
    """Verify invalid auth returns form."""
    api_mock.login.side_effect = NottyAuthError("rejected")
    result = await start(hass, {"email": "test@example.test"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"verification_code": "123456"})
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.usefixtures("api_mock")
async def test_duplicate_account(hass: HomeAssistant) -> None:
    """Verify duplicate account."""
    entry = MockConfigEntry(domain="notty", unique_id="test@example.test", data={})
    entry.add_to_hass(hass)
    result = await start(hass, {"email": "Test@example.test", "password": "pw"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == EXPECTED_ALREADY_CONFIGURED


@pytest.mark.usefixtures("api_mock")
async def test_reauth_replaces_stale_password_with_code_session(hass: HomeAssistant) -> None:
    """Verify reauth replaces stale password with code session."""
    entry = MockConfigEntry(
        domain="notty",
        unique_id="test@example.test",
        version=2,
        data={"email": "test@example.test", "password": "expired"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "notty",
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id, "unique_id": entry.unique_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "test@example.test"})
    with patch("custom_components.notty.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"verification_code": "123456"})
        await hass.async_block_till_done()
    assert result["reason"] == EXPECTED_REAUTH_SUCCESSFUL
    assert EXPECTED_PASSWORD_FIELD not in entry.data
    assert entry.data["access_token"] == EXPECTED_TEST_CREDENTIAL


async def test_connection_error_keeps_code_form(hass: HomeAssistant, api_mock: MagicMock) -> None:
    """Distinguish a transport failure from a rejected email code."""
    api_mock.login.side_effect = NottyApiError("offline")
    result = await start(hass, {"email": "test@example.test"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"verification_code": "123456"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_wrong_reauth_account_does_not_send_code(hass: HomeAssistant, api_mock: MagicMock) -> None:
    """Reject changing the account before contacting the email service."""
    entry = MockConfigEntry(domain="notty", unique_id="test@example.test", data={"email": "test@example.test"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "notty",
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id, "unique_id": entry.unique_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "other@example.test"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == EXPECTED_WRONG_ACCOUNT
    api_mock.request_email_code.assert_not_awaited()
