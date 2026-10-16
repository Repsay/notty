"""Synthetic APK pet contracts and ownership/binding preservation regressions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.notty.api import JsonObject, JsonValue, NottyApi, NottyApiError
from custom_components.notty.feature_contracts import (
    identifier,
    memo_payload,
    object_rows,
    profile_changes,
    profile_payload,
)
from custom_components.notty.pet_api import MemoApi, PetApi

PET_ID = "7"
BOX_ID = "123"
METHOD_GET = "GET"
METHOD_POST = "POST"
FIELD_DEVICE_ID = "user_device_id"
FIELD_OWNER = "is_owner"
FIELD_DEVICES = "pet_devices"
BREED_ID = 9
BREED_NAME = "Synthetic breed"
RESET_CODE = 3
NEW_NAME = "Luna"
PROFILE: JsonObject = {
    "pet_id": 7,
    "name": "Milo",
    "birthday": "2020-05-04",
    "sex": 1,
    "sex_name": "Male",
    "is_sterilization": False,
    "breed_id": 5,
    "breed_name": "Domestic",
    "weight": 4.2,
    "weight_unit": 1,
    "is_owner": True,
    "image_path": "existing-image",
    "collar_id": 8,
    "is_default": False,
    "pet_devices": [{"user_device_id": 123, "is_bind": True}, {"user_device_id": 456, "is_bind": False}],
}
MEMO: JsonObject = {
    "memo_id": 42,
    "title": "Visit",
    "content": "Routine visit",
    "date": "2026-10-16 15:00",
    "remind": True,
    "expired": False,
}
EXPECTED_SEX = 2


def client() -> NottyApi:
    """Create a transport with every HTTP entry point mocked.

    Returns:
        A client that cannot contact the production service.
    """
    api = NottyApi(MagicMock())
    api.pets = AsyncMock(return_value=[{"pet_id": 7}])
    api.request = AsyncMock()
    return api


@pytest.mark.parametrize("value", [True, False, None, 0, -1, 1.0, "", "0", "7/other", "\uff17"])
def test_feature_ids_reject_ambiguous_targets(value: JsonValue) -> None:
    """No Boolean, float or URL fragment can identify a pet or physical device."""
    with pytest.raises(NottyApiError):
        identifier(value)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"pet_id": 99},
        {"user_device_ids": "999"},
        {"weight": 9},
        {"name": "A"},
        {"name": " "},
        {"name": "bad\nname"},
        {"name": "long pet name"},
        {"birthday": "2026-02-30"},
        {"birthday": "20260101"},
        {"sex": True},
        {"sex": 9},
        {"is_sterilization": 1},
        {"breed_id": False},
    ],
)
def test_pet_edits_validate_supported_fields(changes: JsonObject) -> None:
    """Reject identity/binding injection and malformed profile values before HTTP."""
    with pytest.raises(NottyApiError):
        profile_changes(changes)


def test_profile_payload_preserves_only_bound_devices_and_original_values() -> None:
    """The app's user_device_ids string must never bind previously unbound candidates."""
    original = deepcopy(PROFILE)
    payload = profile_payload(PET_ID, original, {"name": NEW_NAME})
    assert payload["name"] == NEW_NAME
    assert payload["user_device_ids"] == BOX_ID
    for field in ("weight", "weight_unit", "image_path", "collar_id", "is_default", "birthday", "sex"):
        assert payload[field] == original[field]
    assert original == PROFILE
    assert FIELD_OWNER not in payload
    assert FIELD_DEVICES not in payload


@pytest.mark.parametrize(
    "changes",
    [
        {"is_owner": False},
        {"is_owner": None},
        {"pet_id": 8},
        {"weight": float("nan")},
        {"weight": 0},
        {"pet_devices": None},
        {"pet_devices": [{"user_device_id": 123}]},
    ],
)
def test_unknown_profile_or_binding_state_prevents_save(changes: JsonObject) -> None:
    """A fresh incomplete profile cannot become a destructive replacement."""
    with pytest.raises(NottyApiError):
        profile_payload(PET_ID, {**PROFILE, **changes}, {"name": NEW_NAME})


async def test_pet_update_exact_wire_and_authoritative_readback() -> None:
    """A successful POST alone must not become optimistic profile state."""
    api = client()
    api.request.side_effect = [PROFILE, {}, PROFILE]
    result = await PetApi(api).update(PET_ID, {"name": NEW_NAME})
    api.request.assert_any_await(
        "POST",
        "/pet/save",
        data={
            "image_path": "existing-image",
            "name": NEW_NAME,
            "breed_id": 5,
            "breed_name": "Domestic",
            "sex": 1,
            "sex_name": "Male",
            "is_sterilization": False,
            "birthday": "2020-05-04",
            "weight": 4.2,
            "collar_id": 8,
            "is_default": False,
            "pet_id": 7,
            "user_device_ids": "123",
            "weight_unit": 1,
        },
    )
    assert result["name"] == PROFILE["name"]


async def test_shared_or_foreign_pets_never_write() -> None:
    """Account membership and fresh ownership are independently required."""
    api = client()
    api.pets.return_value = [{"pet_id": 8}]
    with pytest.raises(NottyApiError):
        await PetApi(api).update(PET_ID, {"name": NEW_NAME})
    api.request.assert_not_awaited()
    api.pets.return_value = [{"pet_id": 7}]
    api.request.return_value = {**PROFILE, "is_owner": False}
    with pytest.raises(NottyApiError):
        await PetApi(api).update(PET_ID, {"name": NEW_NAME})
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)


async def test_concurrent_profile_controls_preserve_both_changes() -> None:
    """Two HA controls sharing an account must not overwrite each other's fresh edits."""
    api = client()
    state = deepcopy(PROFILE)

    async def request(method: str, _path: str, *, data: JsonObject | None = None) -> JsonValue:
        if method == METHOD_GET:
            result = deepcopy(state)
            await asyncio.sleep(0)
            return result
        assert data is not None
        state.update(data)
        return {}

    api.request.side_effect = request
    await asyncio.gather(PetApi(api).update(PET_ID, {"name": NEW_NAME}), PetApi(api).update(PET_ID, {"sex": 2}))
    assert state["name"] == NEW_NAME
    assert state["sex"] == EXPECTED_SEX
    assert state["user_device_ids"] == BOX_ID


async def test_breed_change_uses_server_catalog_name() -> None:
    """A breed ID is not accepted unless the current server catalog contains it."""
    api = client()
    api.request.side_effect = [PROFILE, [{"breed_id": 9, "breed_name": "Synthetic breed"}], {}, PROFILE]
    await PetApi(api).update(PET_ID, {"breed_id": 9})
    post = next(call for call in api.request.await_args_list if call.args[0] == METHOD_POST)
    assert post.kwargs["data"]["breed_id"] == BREED_ID
    assert post.kwargs["data"]["breed_name"] == BREED_NAME


async def test_association_changes_only_one_boolean_binding() -> None:
    """The app serializes a Boolean associate value and integer pet/device IDs."""
    api = client()
    before = [{"pet_id": 7, "is_associated": False}, {"pet_id": 8, "is_associated": True}]
    api.request.side_effect = [PROFILE, before, {}, before]
    result = await PetApi(api).associate(BOX_ID, PET_ID, enabled=True)
    api.request.assert_any_await(
        "POST", "/device/associate_pet", data={"pet_id": 7, "user_device_id": 123, "associate": True}
    )
    assert result == before


@pytest.mark.parametrize("rows", [[{"pet_id": 8, "is_associated": True}], [{"pet_id": 7, "is_associated": None}]])
async def test_unknown_association_target_or_state_never_writes(rows: list[JsonObject]) -> None:
    """Never blindly toggle a pet missing from the selected device's fresh candidates."""
    api = client()
    api.request.side_effect = [PROFILE, rows]
    with pytest.raises(NottyApiError):
        await PetApi(api).associate(BOX_ID, PET_ID, enabled=True)
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)


async def test_create_memo_exact_text_contract() -> None:
    """Create uses memo_id zero, integer pet ID, raw clock text and Boolean reminder."""
    api = client()
    api.request.side_effect = [PROFILE, {}]
    await MemoApi(api).save(PET_ID, {"title": " Visit ", "content": "Routine visit", "date": "2026-10-16 15:00"})
    api.request.assert_awaited_with(
        "POST",
        "/pet/add_memo",
        data={
            "pet_id": 7,
            "memo_id": 0,
            "title": "Visit",
            "content": "Routine visit",
            "date": "2026-10-16 15:00",
            "remind": False,
            "expired": False,
        },
    )


async def test_memo_global_id_requires_fresh_pet_membership() -> None:
    """A memo from another pet cannot be retrieved or edited by guessing its ID."""
    api = client()
    memos = MemoApi(api)
    memos.list_memos = AsyncMock(return_value=[{"memo_id": 99}])
    with pytest.raises(NottyApiError):
        await memos.detail(PET_ID, 42)
    api.request.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"pet_id": 8},
        {"memo_id": 99},
        {"date": "2026-10-16T15:00:00Z"},
        {"remind": 1},
        {"title": ""},
        {"content": "\x00"},
    ],
)
def test_memo_edits_reject_identity_clock_and_state_guessing(changes: JsonObject) -> None:
    """Unsupported timestamps and injected targets cannot become API writes."""
    with pytest.raises(NottyApiError):
        memo_payload(PET_ID, MEMO, changes, create=False)


@pytest.mark.parametrize("value", [None, {}, {"data": None}, [None], [1]])
def test_record_lists_do_not_hide_unavailable_or_malformed_responses(value: JsonValue) -> None:
    """An endpoint failure must not look like an empty association/memo list."""
    with pytest.raises(NottyApiError):
        object_rows(value)


async def test_memo_edit_preserves_omitted_fields_and_native_identity() -> None:
    """Changing content keeps reminder/date/title and targets the listed memo only."""
    api = client()
    api.request.side_effect = [PROFILE, PROFILE, [MEMO], MEMO, {}]
    await MemoApi(api).save(PET_ID, {"content": "Updated visit"}, memo_id=42)
    api.request.assert_awaited_with("POST", "/pet/edit_memo", data={**MEMO, "pet_id": 7, "content": "Updated visit"})


async def test_memo_detail_rejects_a_different_pet_in_readback() -> None:
    """Even a listed global ID cannot override mismatched detail ownership."""
    api = client()
    api.request.side_effect = [PROFILE, [MEMO], {**MEMO, "pet_id": 8}]
    with pytest.raises(NottyApiError, match="another pet"):
        await MemoApi(api).detail(PET_ID, 42)
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)


async def test_shared_pet_cannot_create_a_memo() -> None:
    """Memo edits require the same fresh owner permission as profile changes."""
    api = client()
    api.request.return_value = {**PROFILE, "is_owner": False}
    with pytest.raises(NottyApiError, match="owner"):
        await MemoApi(api).save(PET_ID, {"title": "Visit", "content": "Visit", "date": MEMO["date"]})
    assert all(call.args[0] == METHOD_GET for call in api.request.await_args_list)
