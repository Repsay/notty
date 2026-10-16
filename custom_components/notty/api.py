from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

BASE_URL = "https://api.nottycat.com"
FIREBASE_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
FIREBASE_REFRESH_URL = "https://securetoken.googleapis.com/v1/token"
DEFAULT_FIREBASE_API_KEY = "AIzaSyCm6i6ZT7MAQmdA9rKobMAslpTXRCdXncw"
APP_USER_AGENT = "4.1.0;android;6.0.1;default;A001"
LOGIN_CODE_TYPE_ID = 1
LOGIN_USER_DEVICE_ID = 1
LOGIN_DEVICE_ID = 1
DEFAULT_CLIENT_ID = "0"
DEVICE_INFO_PATHS = {
    "litter_box": "/device/litter_box/get_info/",
}
LITTER_READ_ENDPOINTS = {
    "plans": "/device/litter_box/plans/",
    "guide": "/device/litter_box/get_guide/",
    "pet_data_list": "/device/litter_box/pet_data_list/",
    "messages": "/device/get_message/",
    "daily_event_counts": "/device/get_daily_event_counts/",
    "associated_pets": "/device/get_associated_pets/",
    "associated_users": "/device/get_associated_users/",
    "upgrade": "/device/check_upgrade/",
}
PET_READ_ENDPOINTS = {
    "info": "/pet/info/{pet_id}",
    "wc_statistics": "/pet/pet_wc_data_statistics?pet_id={pet_id}",
    "memos": "/pet/memos/{pet_id}",
    "associated_users": "/pet/get_associated_users/{pet_id}",
}
LITTER_PET_READ_ENDPOINTS = {
    "pet_data_statistics": "/device/litter_box/pet_data_statistics/{device_id}?pet_id={pet_id}",
    "pet_data_detail": "/device/litter_box/pet_data_detail/{device_id}?pet_id={pet_id}",
}
LITTER_ACTION_ENDPOINTS = {
    "one_key": "/device/litter_box/one_key",
    "set_mode": "/device/litter_box/set_mode",
    "set_key": "/device/litter_box/set_key",
    "reset_litter_reminder": "/device/litter_box/set_litter_remind",
    "reset_garbage_bag_reminder": "/device/litter_box/set_garbage_bag_remind",
    "set_litter_reminder_days": "/device/litter_box/set_litter_remind",
    "set_garbage_bag_reminder_days": "/device/litter_box/set_garbage_bag_remind",
    "set_litter_remind": "/device/litter_box/set_litter_remind",
    "set_garbage_bag_remind": "/device/litter_box/set_garbage_bag_remind",
    "set_auto_delay": "/device/litter_box/set_auto_delay",
    "set_dnd": "/device/litter_box/set_dnd",
    "set_language": "/device/litter_box/set_language",
    "add_plan": "/device/litter_box/add_plan",
    "edit_plan": "/device/litter_box/edit_plan",
    "delete_plan": "/device/litter_box/delete_plan",
    "open_plan": "/device/litter_box/open_plan",
    "reset_device_weight": "/device/litter_box/reset_device_weight",
    "horizontal_calibration": "/device/litter_box/horizontal_calibration",
    "confirm_upgrade": "/device/confirm_upgrade",
    "set_alias": "/device/set_alias",
    "change_time_zone": "/device/change_time_zone",
    "clear_statistics": "/device/clear_statistics/",
}
SAFE_LITTER_ACTIONS = (
    "one_key",
    "set_mode",
    "set_key",
    "reset_litter_reminder",
    "reset_garbage_bag_reminder",
    "set_litter_reminder_days",
    "set_garbage_bag_reminder_days",
    "set_dnd",
    "set_language",
    "reset_device_weight",
    "horizontal_calibration",
)
LIST_KEYS = ("list", "devices", "rows", "items", "data")
LITTER_BIND_KEYS = (
    "bind_litter_box",
    "litter_box",
    "litter_box_id",
    "litter_box_user_device_id",
    "lb_user_device_id",
)
_LOGGER = logging.getLogger(__name__)


class NottyApiError(Exception):
    """Base NOTTY API error."""


class NottyAuthError(NottyApiError):
    """Authentication failed."""


class NottyApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        email: str | None = None,
        password: str | None = None,
        verification_code: str | None = None,
        token: str | None = None,
        refresh_token: str | None = None,
        user_id: str | int | None = None,
        firebase_api_key: str | None = None,
        client_id: str = DEFAULT_CLIENT_ID,
        region_code: str = "NL",
    ) -> None:
        self._session = session
        self.email = email.strip() if email else email
        self.password = password
        self.verification_code = (
            verification_code.strip() if verification_code else verification_code
        )
        self.token = token
        self.refresh_token = refresh_token
        self.user_id = str(user_id) if user_id not in (None, "") else None
        self.firebase_api_key = firebase_api_key or DEFAULT_FIREBASE_API_KEY
        self.client_id = client_id
        self.region_code = region_code
        self._authenticating = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en",
            "Content-Type": "application/json",
            "User-Agent": APP_USER_AGENT,
            "User-Aagent": APP_USER_AGENT,
            "HZUID": self.user_id or "2",
            "XJiang-Language": "en",
        }
        if self.region_code:
            headers["xjiang_region_id"] = self.region_code
        if self.token:
            raw_token = self.token.removeprefix("Bearer ").removeprefix("bearer ")
            headers["Authorization"] = raw_token
            headers["access_token"] = raw_token
        return headers

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        if isinstance(payload, dict):
            code = payload.get("code", payload.get("error_code"))
            if code not in (None, 0, 200, "0", "200"):
                message = payload.get("message") or payload.get("msg") or str(payload)
                if str(code) in {"401", "403", "1001", "1002"}:
                    raise NottyAuthError(message)
                raise NottyApiError(message)
            for key in ("data", "result"):
                if key in payload:
                    return payload[key]
        return payload

    async def _raw_request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        headers = (
            self._headers()
            if authenticated
            else {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en",
                "Content-Type": "application/json"
                if form is None
                else "application/x-www-form-urlencoded",
                "User-Agent": APP_USER_AGENT,
                "User-Aagent": APP_USER_AGENT,
                "HZUID": "2",
                "XJiang-Language": "en",
            }
        )
        if not authenticated and self.region_code:
            headers["xjiang_region_id"] = self.region_code
        try:
            async with self._session.request(
                method,
                url,
                json=data,
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                text = await response.text()
                if response.status in (401, 403):
                    raise NottyAuthError(f"HTTP {response.status}")
                if response.status >= 400:
                    raise NottyApiError(f"HTTP {response.status}")
                try:
                    payload = await response.json(content_type=None)
                except Exception:
                    return {"raw": text}
        except asyncio.TimeoutError as err:
            raise NottyApiError("Timeout contacting NOTTY") from err
        except aiohttp.ClientError as err:
            raise NottyApiError(str(err)) from err
        return self._unwrap(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        try:
            return await self._raw_request(method, f"{BASE_URL}{path}", data=data)
        except NottyAuthError:
            if not retry_auth or self._authenticating or not self.email or not self.password:
                raise
            await self.login()
            return await self._request(method, path, data=data, retry_auth=False)

    @staticmethod
    def _find_first(result: Any, keys: tuple[str, ...]) -> Any:
        if isinstance(result, dict):
            for key in keys:
                if key in result and result[key] not in (None, ""):
                    return result[key]
            for value in result.values():
                found = NottyApi._find_first(value, keys)
                if found not in (None, ""):
                    return found
        elif isinstance(result, list):
            for item in result:
                found = NottyApi._find_first(item, keys)
                if found not in (None, ""):
                    return found
        return None

    @staticmethod
    def _as_list(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, dict):
            for key in LIST_KEYS:
                value = result.get(key)
                if isinstance(value, list):
                    result = value
                    break
            else:
                result = []
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, dict)]

    @staticmethod
    def _bound_litter_id(pet: dict[str, Any]) -> str | None:
        for key in LITTER_BIND_KEYS:
            value = pet.get(key)
            if isinstance(value, bool) or value in (None, "", 0, "0"):
                continue
            if isinstance(value, dict):
                found = NottyApi._find_first(
                    value,
                    ("user_device_id", "device_id", "id", "did"),
                )
                if found not in (None, "", 0, "0", False):
                    return str(found)
                continue
            if isinstance(value, list):
                found = NottyApi._find_first(
                    value,
                    ("user_device_id", "device_id", "id", "did"),
                )
                if found not in (None, "", 0, "0", False):
                    return str(found)
                continue
            return str(value)
        return None

    @staticmethod
    def _pet_litter_device_id(pet: dict[str, Any]) -> str | None:
        for key in ("_notty_litter_user_device_id", "litter_user_device_id"):
            value = pet.get(key)
            if value not in (None, "", 0, "0", False):
                return str(value)

        bound_id = NottyApi._bound_litter_id(pet)
        if bound_id:
            return bound_id

        pet_devices = pet.get("pet_devices")
        if isinstance(pet_devices, list):
            for bound_device in pet_devices:
                if not isinstance(bound_device, dict) or bound_device.get("is_bind") is False:
                    continue
                for key in ("user_device_id", "device_id", "id", "did"):
                    found = bound_device.get(key)
                    if found not in (None, "", 0, "0", False):
                        return str(found)
        return None

    @staticmethod
    def _pet_has_litter_data(pet: dict[str, Any]) -> bool:
        if pet.get("bind_litter_box") or pet.get("has_litter_box_data"):
            return True
        for key in (
            "today_wc_count",
            "today_wc_duration",
            "yesterday_wc_count",
            "yesterday_wc_duration",
            "wc_status",
        ):
            if pet.get(key) not in (None, "", 0, "0", False):
                return True
        return False

    @staticmethod
    def _pet_litter_device(pet: dict[str, Any]) -> dict[str, Any] | None:
        device_id = NottyApi._pet_litter_device_id(pet)
        has_litter_data = NottyApi._pet_has_litter_data(pet)
        pet_id = pet.get("pet_id") or pet.get("id")
        if not device_id and (not has_litter_data or pet_id in (None, "")):
            return None
        pet_name = pet.get("alias") or pet.get("name") or pet.get("pet_name")
        device = {
            **pet,
            "_notty_source": "pet",
            "_notty_has_device_id": False,
            "_notty_litter_user_device_id": str(device_id) if device_id else None,
            "device_type": "litter_box",
            "product_name": "Cat Automatic Litter Box",
            "pet_id": pet_id,
            "alias": pet_name or pet.get("alias"),
            "model": "Litter Box Pet",
            "id": f"pet_{pet_id}",
        }
        return device

    @staticmethod
    def _extract_login(result: Any) -> tuple[str | None, str | None, str | None]:
        if not isinstance(result, dict):
            return None, None, None
        token = NottyApi._find_first(result, ("access_token", "accessToken", "token", "idToken"))
        refresh = NottyApi._find_first(result, ("refresh_token", "refreshToken"))
        user_id = result.get("user_id") or result.get("userId") or result.get("uid")
        if user_id in (None, ""):
            user = result.get("user") or result.get("userInfo") or result.get("account")
            user_id = NottyApi._find_first(user, ("user_id", "userId", "uid", "id"))
        return (
            str(token) if token else None,
            str(refresh) if refresh else None,
            str(user_id) if user_id not in (None, "") else None,
        )

    async def request_email_code(self) -> Any:
        if not self.email:
            raise NottyAuthError("Email address is required")
        return await self._raw_request(
            "POST",
            f"{BASE_URL}/account/get_email_code",
            data={
                "email": self.email,
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "client_id": self.client_id,
            },
            authenticated=False,
        )

    async def _login_with_email_code(self) -> bool:
        if not self.email or not self.verification_code:
            return False
        result = await self._raw_request(
            "POST",
            f"{BASE_URL}/account/login_by_email",
            data={
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "email": self.email,
                "code": self.verification_code,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            authenticated=False,
        )
        token, refresh, user_id = self._extract_login(result)
        if token:
            self.token = token
            self.refresh_token = refresh
            self.user_id = user_id
            return True
        _LOGGER.debug("NOTTY email-code login response contained no NOTTY access token")
        return False

    async def _firebase_password_sign_in(self) -> tuple[str, str | None]:
        if not self.firebase_api_key:
            raise NottyAuthError("Firebase API key is required")
        result = await self._raw_request(
            "POST",
            f"{FIREBASE_SIGN_IN_URL}?key={self.firebase_api_key}",
            data={"email": self.email, "password": self.password, "returnSecureToken": True},
            authenticated=False,
        )
        token, refresh, _user_id = self._extract_login(result)
        if not token:
            raise NottyAuthError("Firebase login response contained no ID token")
        return token, refresh

    async def _login_with_firebase(self) -> bool:
        id_token, refresh = await self._firebase_password_sign_in()
        attempts: tuple[dict[str, Any], ...] = (
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "email": self.email,
                "id_token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "email": self.email,
                "idToken": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "email": self.email,
                "access_token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "email": self.email,
                "firebase_token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "email": self.email,
                "token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "id_token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "access_token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
            {
                "code_type_id": LOGIN_CODE_TYPE_ID,
                "token": id_token,
                "user_device_id": LOGIN_USER_DEVICE_ID,
                "device_id": LOGIN_DEVICE_ID,
            },
        )
        errors: list[str] = []
        for payload in attempts:
            try:
                result = await self._raw_request(
                    "POST",
                    f"{BASE_URL}/account/login_by_email",
                    data=payload,
                    authenticated=False,
                )
            except NottyApiError as err:
                errors.append(str(err))
                continue
            token, notty_refresh, user_id = self._extract_login(result)
            if token:
                self.token = token
                self.refresh_token = notty_refresh or refresh
                self.user_id = user_id
                return True
            errors.append("response contained no NOTTY access token")
        _LOGGER.debug("NOTTY Firebase token exchange attempts failed: %s", " | ".join(errors))
        return False

    async def _login_notty(self) -> bool:
        # The Flutter APK exposes account login code and Firebase Auth, but its exact
        # password exchange is AOT compiled. Try known/common NOTTY payload variants.
        attempts: tuple[tuple[str, dict[str, Any]], ...] = (
            (
                "/account/login",
                {
                    "email": self.email,
                    "password": self.password,
                    "user_device_id": LOGIN_USER_DEVICE_ID,
                    "device_id": LOGIN_DEVICE_ID,
                },
            ),
            (
                "/account/login_by_password",
                {
                    "email": self.email,
                    "password": self.password,
                    "user_device_id": LOGIN_USER_DEVICE_ID,
                    "device_id": LOGIN_DEVICE_ID,
                },
            ),
            (
                "/account/login_by_email",
                {
                    "code_type_id": LOGIN_CODE_TYPE_ID,
                    "email": self.email,
                    "password": self.password,
                    "user_device_id": LOGIN_USER_DEVICE_ID,
                    "device_id": LOGIN_DEVICE_ID,
                },
            ),
            (
                "/account/login",
                {
                    "username": self.email,
                    "password": self.password,
                    "user_device_id": LOGIN_USER_DEVICE_ID,
                    "device_id": LOGIN_DEVICE_ID,
                },
            ),
        )
        errors: list[str] = []
        for path, payload in attempts:
            try:
                result = await self._raw_request(
                    "POST", f"{BASE_URL}{path}", data=payload, authenticated=False
                )
            except NottyApiError as err:
                errors.append(f"{path}: {err}")
                continue
            token, refresh, user_id = self._extract_login(result)
            if token:
                self.token = token
                self.refresh_token = refresh
                self.user_id = user_id
                return True
            errors.append(f"{path}: response contained no access token")
        _LOGGER.debug("NOTTY password login attempts failed: %s", " | ".join(errors))
        return False

    async def login(self) -> str:
        """Authenticate without recursively retrying during credential validation."""
        self._authenticating = True
        try:
            return await self._login()
        finally:
            self._authenticating = False

    async def _login(self) -> str:
        if not self.email:
            raise NottyAuthError("Email address is required")

        errors: list[str] = []
        if self.verification_code:
            try:
                if await self._login_with_email_code():
                    await self.devices()
                    return self.token or ""
            except NottyApiError as err:
                errors.append(f"Email code: {err}")

        if self.password:
            try:
                if await self._login_with_firebase():
                    await self.devices()
                    return self.token or ""
            except NottyApiError as err:
                errors.append(f"Firebase/NOTTY: {err}")

            try:
                if await self._login_notty():
                    await self.devices()
                    return self.token or ""
            except NottyApiError as err:
                errors.append(f"NOTTY: {err}")

        if not self.password and not self.verification_code:
            raise NottyAuthError("Password or verification code is required")

        detail = "; ".join(errors) or "No supported login endpoint accepted the credentials"
        raise NottyAuthError(detail)

    async def verify_token(self) -> Any:
        return await self._request("GET", "/account/verify_token", retry_auth=False)

    async def pets(self) -> list[dict[str, Any]]:
        return self._as_list(await self._request("GET", "/pet/list"))

    @staticmethod
    def _litter_pet_ids(pets: list[dict[str, Any]]) -> list[str]:
        pet_ids: list[str] = []
        for pet in pets:
            if not NottyApi._pet_has_litter_data(pet):
                continue
            pet_id = pet.get("pet_id") or pet.get("id")
            if pet_id not in (None, ""):
                pet_ids.append(str(pet_id))
        return pet_ids

    async def user_devices(self, pets: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        errors: list[str] = []
        discovered: dict[str, dict[str, Any]] = {}

        for pet_id in self._litter_pet_ids(pets if pets is not None else await self.pets()):
            try:
                for device in self._as_list(
                    await self._request("GET", f"/device/get_user_devices/{pet_id}")
                ):
                    device_id = str(device.get("user_device_id") or device.get("id") or "")
                    if not device_id:
                        continue
                    pet_ids = set(discovered.get(device_id, {}).get("_notty_pet_ids", []))
                    pet_ids.add(pet_id)
                    discovered[device_id] = {
                        **discovered.get(device_id, {}),
                        **device,
                        "_notty_source": "device",
                        "_notty_has_device_id": True,
                        "_notty_pet_ids": sorted(pet_ids),
                    }
            except NottyAuthError:
                raise
            except NottyApiError as err:
                errors.append(f"GET /device/get_user_devices/{pet_id}: {err}")

        for path in ("/device/get_user_devices/2", "/device/get_user_devices/"):
            try:
                for device in self._as_list(await self._request("GET", path)):
                    device_id = str(device.get("user_device_id") or device.get("id") or "")
                    if device_id:
                        discovered[device_id] = {
                            **discovered.get(device_id, {}),
                            **device,
                            "_notty_source": "device",
                            "_notty_has_device_id": True,
                        }
            except NottyAuthError:
                raise
            except NottyApiError as err:
                errors.append(f"GET {path}: {err}")

        if discovered:
            return list(discovered.values())
        if errors:
            raise NottyApiError("; ".join(errors))
        return []

    async def devices(self) -> list[dict[str, Any]]:
        errors: list[str] = []
        discovered: dict[str, dict[str, Any]] = {}
        account_endpoint_ok = False

        try:
            pets = await self.pets()
        except NottyAuthError:
            raise
        except NottyApiError as err:
            pets = []
            errors.append(f"/pet/list: {err}")

        try:
            for device in await self.user_devices(pets):
                device_id = str(device.get("user_device_id") or device.get("id") or "")
                if device_id:
                    discovered[device_id] = device
            account_endpoint_ok = True
        except NottyAuthError:
            raise
        except NottyApiError as err:
            errors.append(f"/device/get_user_devices/<pet_id>: {err}")

        pet_parents: dict[str, set[str]] = {}
        for physical in discovered.values():
            parent_id = physical.get("user_device_id")
            if parent_id in (None, ""):
                continue
            for pet_id in physical.get("_notty_pet_ids") or []:
                pet_parents.setdefault(str(pet_id), set()).add(str(parent_id))

        for pet in pets:
            device = self._pet_litter_device(pet)
            if device:
                # Boolean bind_litter_box indicates a binding, but provides no device ID.
                parents = pet_parents.get(str(device["pet_id"]), set())
                if not device.get("_notty_litter_user_device_id") and len(parents) == 1:
                    device["_notty_litter_user_device_id"] = next(iter(parents))
                device_id = str(device.get("id"))
                discovered[device_id] = {
                    **discovered.get(device_id, {}),
                    **device,
                }
        if pets:
            account_endpoint_ok = True

        if discovered or account_endpoint_ok:
            return list(discovered.values())
        raise NottyApiError(
            "; ".join(errors) or "No supported device list endpoint returned devices"
        )

    @staticmethod
    def _device_payload(device_id: str) -> dict[str, str]:
        return {"user_device_id": device_id, "device_id": device_id}

    async def device_info(self, device_id: str, device_type: str) -> dict[str, Any]:
        base_path = DEVICE_INFO_PATHS.get(device_type)
        if not base_path:
            return {}

        for method, path, data in (
            ("GET", f"{base_path}{device_id}", None),
            ("GET", base_path, self._device_payload(device_id)),
            ("POST", base_path, self._device_payload(device_id)),
        ):
            try:
                result = await self._request(
                    method,
                    path,
                    data=data,
                )
                return result if isinstance(result, dict) else {"data": result}
            except NottyAuthError:
                raise
            except NottyApiError:
                continue
        return {}

    async def litter_info(self, device_id: str) -> dict[str, Any]:
        return await self.device_info(device_id, "litter_box")

    async def litter_related_info(self, device_id: str) -> dict[str, Any]:
        related: dict[str, Any] = {}
        payload = self._device_payload(device_id)
        for key, base_path in LITTER_READ_ENDPOINTS.items():
            for method, path, data in (
                ("GET", f"{base_path}{device_id}", None),
                ("POST", base_path, payload),
            ):
                try:
                    result = await self._request(method, path, data=data)
                except NottyAuthError:
                    raise
                except NottyApiError:
                    continue
                related[key] = result
                if isinstance(result, list):
                    related[f"{key}_count"] = len(result)
                elif isinstance(result, dict):
                    items = self._as_list(result)
                    if items:
                        related[f"{key}_count"] = len(items)
                break

        pet_rows: dict[str, dict[str, Any]] = {}
        for source_key in ("associated_pets", "pet_data_list"):
            for row in self._as_list(related.get(source_key)):
                pet_id = row.get("pet_id") or row.get("id")
                if pet_id in (None, ""):
                    continue
                pet_rows.setdefault(str(pet_id), {}).update(row)

        for key, template in LITTER_PET_READ_ENDPOINTS.items():
            rows: list[dict[str, Any]] = []
            for pet_id, pet_row in pet_rows.items():
                try:
                    result = await self._request(
                        "GET",
                        template.format(device_id=device_id, pet_id=pet_id),
                    )
                except NottyAuthError:
                    raise
                except NottyApiError:
                    continue
                if result in (None, ""):
                    continue
                row = {
                    "pet_id": pet_id,
                    "name": pet_row.get("name") or pet_row.get("alias"),
                    key: result,
                }
                rows.append({k: v for k, v in row.items() if v not in (None, "")})
            if rows:
                related[key] = rows
                related[f"{key}_count"] = len(rows)
        return related

    async def pet_related_info(self, pet_id: str) -> dict[str, Any]:
        related: dict[str, Any] = {}
        for key, base_path in PET_READ_ENDPOINTS.items():
            try:
                result = await self._request("GET", base_path.format(pet_id=pet_id))
            except NottyAuthError:
                raise
            except NottyApiError:
                continue
            related[key] = result
            if isinstance(result, list):
                related[f"{key}_count"] = len(result)
            elif isinstance(result, dict):
                items = self._as_list(result)
                if items:
                    related[f"{key}_count"] = len(items)
        return related

    async def unread_message_count(self) -> int | None:
        result = await self._request("GET", "/message/get_unread_count")
        return result if isinstance(result, int) else None

    async def save_pet(self, pet_id: str, data: dict[str, Any]) -> Any:
        payload = {"pet_id": pet_id, **data}
        return await self._request("POST", "/pet/save", data=payload)

    async def associate_pet(self, device_id: str, pet_id: str, associate: bool = True) -> Any:
        return await self._request(
            "POST",
            "/device/associate_pet",
            data={
                "user_device_id": device_id,
                "pet_id": pet_id,
                "associate": associate,
            },
        )

    async def save_pet_weight(self, pet_id: str, weight: float, current: dict[str, Any]) -> Any:
        pet_devices = current.get("pet_devices")
        litter_device_id = self._pet_litter_device_id(current)
        has_litter_binding = bool(
            litter_device_id or current.get("bind_litter_box") or current.get("has_litter_box_data")
        )
        if has_litter_binding and not litter_device_id:
            raise NottyApiError(
                "Refusing to update cat weight without the current litter-box binding data"
            )
        payload = {
            "name": current.get("name") or current.get("alias"),
            "birthday": current.get("birthday"),
            "breed_id": current.get("breed_id"),
            "sex": current.get("sex"),
            "weight": weight,
            "is_sterilization": current.get("is_sterilization"),
            "collar_id": current.get("collar_id") or 0,
            "image_path": current.get("image_path") or "",
        }
        if isinstance(pet_devices, list):
            payload["pet_devices"] = pet_devices
        for key in ("bind_litter_box", "bind_feeder", "bind_water_dispenser"):
            if key in current:
                payload[key] = current[key]
        result = await self.save_pet(
            pet_id,
            {key: value for key, value in payload.items() if value not in (None, "")},
        )
        if litter_device_id:
            await self.associate_pet(litter_device_id, pet_id, True)
        return result

    async def command(self, device_id: str, action: Any, device_type: str = "litter_box") -> Any:
        return await self._request(
            "POST",
            f"/device/{device_type}/one_key",
            data={
                "user_device_id": device_id,
                "one_key": action,
            },
        )

    async def endpoint_action(self, device_id: str, path: str) -> Any:
        return await self._request("POST", path, data=self._device_payload(device_id))

    async def litter_action(
        self, device_id: str, action: str, data: dict[str, Any] | None = None
    ) -> Any:
        path = LITTER_ACTION_ENDPOINTS.get(action)
        if not path:
            raise NottyApiError(f"Unsupported litter box action: {action}")
        payload = {**(data or {}), **self._device_payload(device_id)}
        if action == "one_key" and "one_key" not in payload:
            raise NottyApiError("one_key action requires a one_key value")
        return await self._request("POST", path, data=payload)
