from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.notty.api import NottyAuthError


async def start(hass, data):
    return await hass.config_entries.flow.async_init(
        "notty", context={"source": config_entries.SOURCE_USER}, data=data
    )


async def test_password_login(hass, api_mock):
    with patch("custom_components.notty.async_setup_entry", return_value=True):
        result = await start(hass, {"email": "Test@example.test", "password": "pw"})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "test@example.test"
    assert result["data"]["access_token"] == "test-token"


async def test_email_code_login_does_not_store_code(hass, api_mock):
    result = await start(hass, {"email": "test@example.test"})
    assert result["step_id"] == "code"
    api_mock.request_email_code.assert_awaited_once()
    with patch("custom_components.notty.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"verification_code": "123456"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "verification_code" not in result["data"]


async def test_invalid_auth_returns_form(hass, api_mock):
    api_mock.login.side_effect = NottyAuthError("rejected")
    result = await start(hass, {"email": "test@example.test", "password": "pw"})
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_account(hass, api_mock):
    entry = MockConfigEntry(domain="notty", unique_id="test@example.test", data={})
    entry.add_to_hass(hass)
    result = await start(hass, {"email": "Test@example.test", "password": "pw"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_replaces_stale_password_with_code_session(hass, api_mock):
    entry = MockConfigEntry(
        domain="notty",
        unique_id="test@example.test",
        version=2,
        data={"email": "test@example.test", "password": "expired"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "notty",
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": "test@example.test"}
    )
    with patch("custom_components.notty.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"verification_code": "123456"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert "password" not in entry.data
    assert entry.data["access_token"] == "test-token"
