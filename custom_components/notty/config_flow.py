"""Configure NOTTY using the APK-backed email verification flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.notty.api import JsonObject, NottyApi, NottyApiError, NottyAuthError
from custom_components.notty.const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_REFRESH_TOKEN,
    CONF_REGION_CODE,
    CONF_USER_ID,
    CONF_VERIFICATION_CODE,
    CONFIG_ENTRY_VERSION,
    DEFAULT_REGION_CODE,
    DOMAIN,
)
from custom_components.notty.validation import vol

# Home Assistant ConfigFlowResult embeds framework-owned Any fields.
# mypy: disallow-any-expr=False


class NottyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = CONFIG_ENTRY_VERSION
    _last_error: str = ""
    _email: str = ""
    _region_code: str = DEFAULT_REGION_CODE

    async def async_step_reauth(self, entry_data: JsonObject) -> ConfigFlowResult:
        """Start email-code reauthentication for an expired session.

        Returns:
            The account identification form.
        """
        del entry_data
        return await self.async_step_user()

    async def async_step_user(self, user_input: JsonObject | None = None) -> ConfigFlowResult:
        """Identify the account and request one email verification code.

        Returns:
            The code form or a recoverable account-form error.
        """
        errors: dict[str, str] = {}
        if user_input:
            self._email = str(user_input[CONF_EMAIL]).strip()
            self._region_code = str(user_input.get(CONF_REGION_CODE) or DEFAULT_REGION_CODE)
            await self.async_set_unique_id(self._email.lower())
            if self.source == config_entries.SOURCE_REAUTH:
                self._abort_if_unique_id_mismatch(reason="wrong_account")
            else:
                self._abort_if_unique_id_configured()
            api = NottyApi(async_get_clientsession(self.hass), email=self._email, region_code=self._region_code)
            try:
                await api.request_email_code()
            except NottyApiError as err:
                errors["base"] = "cannot_send_code"
                self._last_error = str(err)
            else:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): str,
                vol.Optional(CONF_REGION_CODE, default=DEFAULT_REGION_CODE): str,
            }),
            errors=errors,
            description_placeholders={"error": self._last_error},
        )

    async def async_step_code(self, user_input: JsonObject | None = None) -> ConfigFlowResult:
        """Exchange the user-supplied code without persisting it.

        Returns:
            A new entry, completed reauthentication, or the code form.
        """
        errors: dict[str, str] = {}
        if user_input:
            api = NottyApi(
                async_get_clientsession(self.hass),
                email=self._email,
                region_code=self._region_code,
                verification_code=str(user_input[CONF_VERIFICATION_CODE]),
            )
            try:
                await api.login()
            except NottyAuthError as err:
                errors["base"] = "invalid_auth"
                self._last_error = str(err)
            except NottyApiError as err:
                errors["base"] = "cannot_connect"
                self._last_error = str(err)
            else:
                data: JsonObject = {
                    CONF_EMAIL: self._email,
                    CONF_REGION_CODE: self._region_code,
                    CONF_ACCESS_TOKEN: api.token,
                }
                if api.user_id:
                    data[CONF_USER_ID] = api.user_id
                if api.refresh_token:
                    data[CONF_REFRESH_TOKEN] = api.refresh_token
                if self.source == config_entries.SOURCE_REAUTH:
                    return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
                return self.async_create_entry(title=self._email, data=data)
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_VERIFICATION_CODE): str}),
            errors=errors,
            description_placeholders={"email": self._email, "error": self._last_error},
        )
