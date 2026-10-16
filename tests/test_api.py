from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.notty.api import NottyApi, NottyApiError, NottyAuthError

EXPECTED_API_RAW_REQUEST_AWAIT_COUNT = 2
EXPECTED_ABC = "abc"
EXPECTED_42 = "42"
EXPECTED_PAYLOAD_WEIGHT = 4.5
EXPECTED_BOX_1 = "box-1"
EXPECTED_LEN_DEVICES = 2
EXPECTED_PET_9 = "pet_9"
EXPECTED_9001 = "9001"


@pytest.mark.parametrize("code", [0, 200, "0", "200"])
def test_unwrap_success(code: int | str) -> None:
    """Verify unwrap success."""
    assert NottyApi.unwrap({"code": code, "data": {"online": True}}) == {"online": True}


@pytest.mark.parametrize(("code", "error"), [(401, NottyAuthError), (1002, NottyAuthError), (500, NottyApiError)])
def test_unwrap_errors(code: int | str, error: type[Exception]) -> None:
    """Verify unwrap errors."""
    with pytest.raises(error):
        NottyApi.unwrap({"code": code, "message": "rejected"})


async def test_retry_auth_once() -> None:
    """Verify retry auth once."""
    api = NottyApi(MagicMock(), email="test@example.test", password=SAMPLE_CREDENTIAL)
    api.raw_request = AsyncMock(side_effect=[NottyAuthError(), NottyAuthError()])
    api.login = AsyncMock()
    with pytest.raises(NottyAuthError):
        await api.request("GET", "/pet/list")
    api.login.assert_awaited_once()
    assert api.raw_request.await_count == EXPECTED_API_RAW_REQUEST_AWAIT_COUNT


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("devices", []),
        ("user_devices", [[]]),
        ("litter_info", ["box-1"]),
        ("litter_related_info", ["box-1"]),
        ("pet_related_info", ["cat-1"]),
    ],
)
async def test_read_fallbacks_do_not_swallow_auth_failures(method: str, args: list[object]) -> None:
    """Verify read fallbacks do not swallow auth failures."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(side_effect=NottyAuthError("expired"))
    with pytest.raises(NottyAuthError):
        await getattr(api, method)(*args)


async def test_login_validation_does_not_recurse() -> None:
    """Verify login validation does not recurse."""
    api = NottyApi(MagicMock(), email="test@example.test", password=SAMPLE_CREDENTIAL)
    api.login_with_firebase = AsyncMock(return_value=True)
    api.login_notty = AsyncMock(return_value=True)
    api.raw_request = AsyncMock(side_effect=NottyAuthError("expired"))
    with pytest.raises(NottyAuthError):
        await api.login()
    assert api.login_with_firebase.await_count == 1
    assert api.login_notty.await_count == 1
    assert not api.authenticating


async def test_code_login_extracts_credentials() -> None:
    """Verify code login extracts credentials."""
    api = NottyApi(MagicMock(), email="test@example.test", verification_code="123456")
    api.raw_request = AsyncMock(return_value={"access_token": "abc", "user_id": 42})
    api.devices = AsyncMock(return_value=[])
    assert await api.login() == EXPECTED_ABC
    assert api.user_id == EXPECTED_42


async def test_weight_write_preserves_binding() -> None:
    """Verify weight write preserves binding."""
    api = NottyApi(MagicMock())
    api.save_pet = AsyncMock()
    api.associate_pet = AsyncMock()
    current = {"name": "Test cat", "bind_litter_box": "box-1", "pet_devices": [{"user_device_id": "box-1"}]}
    await api.save_pet_weight("cat-1", 4.5, current)
    payload = api.save_pet.call_args.args[1]
    assert payload["weight"] == EXPECTED_PAYLOAD_WEIGHT
    assert payload["bind_litter_box"] == EXPECTED_BOX_1
    assert payload["pet_devices"] == current["pet_devices"]
    api.associate_pet.assert_awaited_once_with("box-1", "cat-1", associate=True)


async def test_weight_write_refuses_missing_binding() -> None:
    """Verify weight write refuses missing binding."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError, match="binding"):
        await api.save_pet_weight("cat-1", 4.5, {"has_litter_box_data": True})
    api.request.assert_not_called()


async def test_devices_keep_pets_separate_from_hardware() -> None:
    """Verify devices keep pets separate from hardware."""
    api = NottyApi(MagicMock())
    api.pets = AsyncMock(return_value=[{"pet_id": 9, "name": "Test", "bind_litter_box": 42}])
    api.user_devices = AsyncMock(return_value=[{"user_device_id": 42, "device_type": "litter_box"}])
    devices = await api.devices()
    assert len(devices) == EXPECTED_LEN_DEVICES
    assert devices[1]["id"] == EXPECTED_PET_9
    assert devices[1]["_notty_litter_user_device_id"] == EXPECTED_42
    assert devices[1]["_notty_has_device_id"] is False


async def test_unsupported_action_never_sent() -> None:
    """Verify unsupported action never sent."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError):
        await api.litter_action("box-1", "unknown")
    with pytest.raises(NottyApiError):
        await api.litter_action("box-1", "one_key")
    api.request.assert_not_called()


async def test_action_payload_cannot_override_selected_device() -> None:
    """Verify action payload cannot override selected device."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    await api.litter_action("box-1", "set_mode", {"mode": 2, "user_device_id": "box-2", "device_id": "box-2"})
    assert api.request.call_args.kwargs["data"] == {"mode": 2, "user_device_id": "box-1", "device_id": "box-1"}


@pytest.mark.parametrize(("status", "error"), [(401, NottyAuthError), (500, NottyApiError)])
async def test_http_errors_do_not_echo_response_body(status: int, error: type[Exception]) -> None:
    """Verify http errors do not echo response body."""
    response = MagicMock(status=status)
    response.text = AsyncMock(return_value="private-account-information")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    session = MagicMock()
    session.request.return_value = context
    with pytest.raises(error, match=f"^HTTP {status}$"):
        await NottyApi(session).raw_request("GET", "https://api.nottycat.com/pet/list")


@pytest.mark.parametrize("failure", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_network_errors(failure: Exception) -> None:
    """Verify network errors."""
    session = MagicMock()
    session.request.side_effect = failure
    with pytest.raises(NottyApiError):
        await NottyApi(session).raw_request("GET", "https://api.nottycat.com/pet/list")


async def test_boolean_pet_binding_resolves_from_discovered_physical_box() -> None:
    """Verify boolean pet binding resolves from discovered physical box."""
    api = NottyApi(MagicMock())
    api.pets = AsyncMock(
        return_value=[
            {"pet_id": 101, "name": "Alpha", "bind_litter_box": True},
            {"pet_id": 102, "name": "Beta", "bind_litter_box": True},
        ]
    )
    api.user_devices = AsyncMock(
        return_value=[
            {
                "user_device_id": 9001,
                "device_name": "Cat Automatic Litter Box",
                "_notty_source": "device",
                "_notty_pet_ids": ["101", "102"],
            }
        ]
    )
    devices = await api.devices()
    assert {device["id"]: device["_notty_litter_user_device_id"] for device in devices[1:]} == {
        "pet_101": "9001",
        "pet_102": "9001",
    }


def test_bound_pet_devices_prefer_physical_user_device_id() -> None:
    """Verify bound pet devices prefer physical user device id."""
    pet = {
        "bind_litter_box": True,
        "pet_devices": [
            {"is_bind": False, "user_device_id": 8888},
            {"is_bind": True, "user_device_id": 9001, "device_id": 2},
        ],
    }
    assert NottyApi.pet_litter_device_id(pet) == EXPECTED_9001
    assert NottyApi.pet_litter_device(pet | {"pet_id": 101})["_notty_litter_user_device_id"] == EXPECTED_9001


SAMPLE_CREDENTIAL = "test"
