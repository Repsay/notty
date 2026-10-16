from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.notty.api import NottyApi, NottyApiError, NottyAuthError


@pytest.mark.parametrize("code", [0, 200, "0", "200"])
def test_unwrap_success(code):
    assert NottyApi._unwrap({"code": code, "data": {"online": True}}) == {"online": True}


@pytest.mark.parametrize(
    "code,error", [(401, NottyAuthError), (1002, NottyAuthError), (500, NottyApiError)]
)
def test_unwrap_errors(code, error):
    with pytest.raises(error):
        NottyApi._unwrap({"code": code, "message": "rejected"})


async def test_retry_auth_once():
    api = NottyApi(MagicMock(), email="test@example.test", password="test")
    api._raw_request = AsyncMock(side_effect=[NottyAuthError(), NottyAuthError()])
    api.login = AsyncMock()
    with pytest.raises(NottyAuthError):
        await api._request("GET", "/pet/list")
    api.login.assert_awaited_once()
    assert api._raw_request.await_count == 2


@pytest.mark.parametrize(
    "method,args",
    [
        ("devices", []),
        ("user_devices", [[]]),
        ("litter_info", ["box-1"]),
        ("litter_related_info", ["box-1"]),
        ("pet_related_info", ["cat-1"]),
    ],
)
async def test_read_fallbacks_do_not_swallow_auth_failures(method, args):
    api = NottyApi(MagicMock())
    api._request = AsyncMock(side_effect=NottyAuthError("expired"))
    with pytest.raises(NottyAuthError):
        await getattr(api, method)(*args)


async def test_login_validation_does_not_recurse():
    api = NottyApi(MagicMock(), email="test@example.test", password="test")
    api._login_with_firebase = AsyncMock(return_value=True)
    api._login_notty = AsyncMock(return_value=True)
    api._raw_request = AsyncMock(side_effect=NottyAuthError("expired"))
    with pytest.raises(NottyAuthError):
        await api.login()
    assert api._login_with_firebase.await_count == 1
    assert api._login_notty.await_count == 1
    assert not api._authenticating


async def test_code_login_extracts_credentials():
    api = NottyApi(MagicMock(), email="test@example.test", verification_code="123456")
    api._raw_request = AsyncMock(return_value={"access_token": "abc", "user_id": 42})
    api.devices = AsyncMock(return_value=[])
    assert await api.login() == "abc"
    assert api.user_id == "42"


async def test_weight_write_preserves_binding():
    api = NottyApi(MagicMock())
    api.save_pet = AsyncMock()
    api.associate_pet = AsyncMock()
    current = {
        "name": "Test cat",
        "bind_litter_box": "box-1",
        "pet_devices": [{"user_device_id": "box-1"}],
    }
    await api.save_pet_weight("cat-1", 4.5, current)
    payload = api.save_pet.call_args.args[1]
    assert payload["weight"] == 4.5
    assert payload["bind_litter_box"] == "box-1"
    assert payload["pet_devices"] == current["pet_devices"]
    api.associate_pet.assert_awaited_once_with("box-1", "cat-1", True)


async def test_weight_write_refuses_missing_binding():
    api = NottyApi(MagicMock())
    api._request = AsyncMock()
    with pytest.raises(NottyApiError, match="binding"):
        await api.save_pet_weight("cat-1", 4.5, {"has_litter_box_data": True})
    api._request.assert_not_called()


async def test_devices_keep_pets_separate_from_hardware():
    api = NottyApi(MagicMock())
    api.pets = AsyncMock(return_value=[{"pet_id": 9, "name": "Test", "bind_litter_box": 42}])
    api.user_devices = AsyncMock(return_value=[{"user_device_id": 42, "device_type": "litter_box"}])
    devices = await api.devices()
    assert len(devices) == 2
    assert devices[1]["id"] == "pet_9"
    assert devices[1]["_notty_litter_user_device_id"] == "42"
    assert devices[1]["_notty_has_device_id"] is False


async def test_unsupported_action_never_sent():
    api = NottyApi(MagicMock())
    api._request = AsyncMock()
    with pytest.raises(NottyApiError):
        await api.litter_action("box-1", "unknown")
    with pytest.raises(NottyApiError):
        await api.litter_action("box-1", "one_key")
    api._request.assert_not_called()


async def test_action_payload_cannot_override_selected_device():
    api = NottyApi(MagicMock())
    api._request = AsyncMock()
    await api.litter_action(
        "box-1", "set_mode", {"mode": 2, "user_device_id": "box-2", "device_id": "box-2"}
    )
    assert api._request.call_args.kwargs["data"] == {
        "mode": 2,
        "user_device_id": "box-1",
        "device_id": "box-1",
    }


@pytest.mark.parametrize("status,error", [(401, NottyAuthError), (500, NottyApiError)])
async def test_http_errors_do_not_echo_response_body(status, error):
    response = MagicMock(status=status)
    response.text = AsyncMock(return_value="private-account-information")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    session = MagicMock()
    session.request.return_value = context
    with pytest.raises(error, match=f"^HTTP {status}$"):
        await NottyApi(session)._raw_request("GET", "https://api.nottycat.com/pet/list")


@pytest.mark.parametrize("failure", [TimeoutError(), aiohttp.ClientConnectionError()])
async def test_network_errors(failure):
    session = MagicMock()
    session.request.side_effect = failure
    with pytest.raises(NottyApiError):
        await NottyApi(session)._raw_request("GET", "https://api.nottycat.com/pet/list")


async def test_boolean_pet_binding_resolves_from_discovered_physical_box():
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


def test_bound_pet_devices_prefer_physical_user_device_id():
    pet = {
        "bind_litter_box": True,
        "pet_devices": [
            {"is_bind": False, "user_device_id": 8888},
            {"is_bind": True, "user_device_id": 9001, "device_id": 2},
        ],
    }
    assert NottyApi._pet_litter_device_id(pet) == "9001"
    assert (
        NottyApi._pet_litter_device(pet | {"pet_id": 101})["_notty_litter_user_device_id"] == "9001"
    )
