from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NottyApi, NottyApiError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EMAIL,
    CONF_FIREBASE_API_KEY,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_REGION_CODE,
    CONF_USER_ID,
    CONF_VERIFICATION_CODE,
    DEFAULT_REGION_CODE,
    DOMAIN,
)


class NottyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_reauth(self, entry_data):
        """Allow expired sessions, including code-only sessions, to sign in again."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            password = user_input.get(CONF_PASSWORD) or None
            if not password:
                self._email = user_input[CONF_EMAIL]
                self._region_code = user_input.get(CONF_REGION_CODE, DEFAULT_REGION_CODE)
                self._firebase_api_key = user_input.get(CONF_FIREBASE_API_KEY) or None
                api = NottyApi(
                    async_get_clientsession(self.hass),
                    email=self._email,
                    firebase_api_key=self._firebase_api_key,
                    region_code=self._region_code,
                )
                try:
                    await api.request_email_code()
                except NottyApiError as err:
                    errors["base"] = "cannot_send_code"
                    self._last_error = str(err)
                else:
                    return await self.async_step_code()

            if not errors:
                return await self._create_entry_from_login(
                    {
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: password,
                        CONF_REGION_CODE: user_input.get(CONF_REGION_CODE, DEFAULT_REGION_CODE),
                        CONF_FIREBASE_API_KEY: user_input.get(CONF_FIREBASE_API_KEY) or None,
                    }
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Optional(CONF_REGION_CODE, default=DEFAULT_REGION_CODE): str,
                vol.Optional(CONF_FIREBASE_API_KEY): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"error": getattr(self, "_last_error", "")},
        )

    async def async_step_code(self, user_input=None):
        errors = {}
        if user_input:
            return await self._create_entry_from_login(
                {
                    CONF_EMAIL: self._email,
                    CONF_VERIFICATION_CODE: user_input[CONF_VERIFICATION_CODE],
                    CONF_REGION_CODE: self._region_code,
                    CONF_FIREBASE_API_KEY: self._firebase_api_key,
                }
            )

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_VERIFICATION_CODE): str}),
            errors=errors,
            description_placeholders={
                "email": self._email,
                "error": getattr(self, "_last_error", ""),
            },
        )

    async def _create_entry_from_login(self, user_input):
        errors = {}
        api = NottyApi(
            async_get_clientsession(self.hass),
            email=user_input[CONF_EMAIL],
            password=user_input.get(CONF_PASSWORD),
            verification_code=user_input.get(CONF_VERIFICATION_CODE),
            firebase_api_key=user_input.get(CONF_FIREBASE_API_KEY) or None,
            region_code=user_input.get(CONF_REGION_CODE, DEFAULT_REGION_CODE),
        )
        try:
            await api.login()
        except NottyApiError as err:
            errors["base"] = "invalid_auth"
            self._last_error = str(err)
            step_id = "code" if user_input.get(CONF_VERIFICATION_CODE) else "user"
            schema = (
                vol.Schema({vol.Required(CONF_VERIFICATION_CODE): str})
                if step_id == "code"
                else vol.Schema(
                    {
                        vol.Required(CONF_EMAIL): str,
                        vol.Optional(CONF_PASSWORD): str,
                        vol.Optional(CONF_REGION_CODE, default=DEFAULT_REGION_CODE): str,
                        vol.Optional(CONF_FIREBASE_API_KEY): str,
                    }
                )
            )
            return self.async_show_form(
                step_id=step_id,
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "email": user_input[CONF_EMAIL],
                    "error": getattr(self, "_last_error", ""),
                },
            )
        else:
            await self.async_set_unique_id(user_input[CONF_EMAIL].strip().lower())
            if self.source == config_entries.SOURCE_REAUTH:
                self._abort_if_unique_id_mismatch()
            else:
                self._abort_if_unique_id_configured()
            data = {k: v for k, v in user_input.items() if v and k != CONF_VERIFICATION_CODE}
            data[CONF_ACCESS_TOKEN] = api.token
            if api.user_id:
                data[CONF_USER_ID] = api.user_id
            if api.refresh_token:
                data[CONF_REFRESH_TOKEN] = api.refresh_token
            if self.source == config_entries.SOURCE_REAUTH:
                # Replace old credentials, so a password-to-code switch does not
                # retain an invalid password or old tokens.
                return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
            return self.async_create_entry(
                title=user_input[CONF_EMAIL],
                data=data,
            )
