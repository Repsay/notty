"""Pet profile, association and text-memo requests traced from the Android app."""

from __future__ import annotations

from custom_components.notty.api import JsonObject, JsonValue, NottyApi, NottyApiError, plan_enabled
from custom_components.notty.feature_contracts import (
    FIELD_BREED,
    FIELD_SEX,
    identifier,
    memo_payload,
    object_rows,
    profile_changes,
    profile_payload,
    require_owner,
)


class PetApi:
    """Account-scoped profile edits with fresh ownership and binding readback."""

    def __init__(self, api: NottyApi) -> None:
        self.api = api

    async def profile(self, pet_id: str) -> JsonObject:
        """Read a pet belonging to the current account, rejecting identity mismatch.

        Returns:
            The fresh server profile, including current binding/ownership metadata.

        Raises:
            NottyApiError: If the pet is absent or the response is invalid.
        """
        selected = identifier(pet_id)
        pets = await self.api.pets()
        if not any(identifier(row.get("pet_id")) == selected for row in pets):
            msg = "The selected pet does not belong to this NOTTY account"
            raise NottyApiError(msg)
        value = await self.api.request("GET", f"/pet/info/{selected}")
        if not isinstance(value, dict) or identifier(value.get("pet_id")) != selected:
            msg = "Pet profile readback does not match the selected pet"
            raise NottyApiError(msg)
        return value

    async def breeds(self) -> list[JsonObject]:
        """Read the public catalog rather than inventing breed IDs.

        Returns:
            Server breed IDs and names.

        Raises:
            NottyApiError: If the catalog contains malformed or duplicate records.
        """
        rows = object_rows(await self.api.request("GET", "/pet/breeds"))
        seen: set[int] = set()
        result: list[JsonObject] = []
        for row in rows:
            breed_id = identifier(row.get("breed_id"))
            name = row.get("breed_name")
            if breed_id in seen or not isinstance(name, str) or not name.strip():
                msg = "NOTTY returned an invalid breed catalog"
                raise NottyApiError(msg)
            seen.add(breed_id)
            result.append({"breed_id": breed_id, "breed_name": name})
        return result

    async def update(self, pet_id: str, changes: JsonObject) -> JsonObject:
        """Save supported edits while preserving current images, units and all bindings.

        Returns:
            Fresh profile readback; a successful write alone is not confirmation.

        """
        async with self.api.mutation_lock(f"pet:{identifier(pet_id)}"):
            return await self._update(pet_id, changes)

    async def _update(self, pet_id: str, changes: JsonObject) -> JsonObject:
        changes = profile_changes(changes)
        current = await self.profile(pet_id)
        payload = profile_payload(pet_id, current, changes)
        if FIELD_BREED in changes:
            match = next((row for row in await self.breeds() if row["breed_id"] == changes["breed_id"]), None)
            if match is None:
                msg = "Choose a breed from the current NOTTY breed catalog"
                raise NottyApiError(msg)
            payload["breed_name"] = match["breed_name"]
        if FIELD_SEX in changes:
            payload["sex_name"] = "弟弟" if changes["sex"] == 1 else "妹妹"
        if all(current.get(key) == value for key, value in changes.items()):
            return current
        await self.api.request("POST", "/pet/save", data=payload)
        try:
            return await self.profile(pet_id)
        except NottyApiError as exc:
            msg = "Pet write was acknowledged, but profile readback failed; refresh before retrying"
            raise NottyApiError(msg) from exc

    async def associations(self, device_id: str) -> list[JsonObject]:
        """Read pet candidates and binding states for one selected litter box.

        Returns:
            Fresh device association records.
        """
        return object_rows(await self.api.request("GET", f"/device/get_associated_pets/{identifier(device_id)}"))

    async def associate(self, device_id: str, pet_id: str, *, enabled: bool) -> list[JsonObject]:
        """Change exactly one known association, preserving every other pet binding.

        Returns:
            Fresh association readback.

        """
        async with self.api.mutation_lock(f"pet:{identifier(pet_id)}"):
            return await self._associate(device_id, pet_id, enabled=enabled)

    async def _associate(self, device_id: str, pet_id: str, *, enabled: bool) -> list[JsonObject]:
        current = await self.profile(pet_id)
        require_owner(current)
        selected = identifier(pet_id)
        rows = await self.associations(device_id)
        matches = [row for row in rows if identifier(row.get("pet_id")) == selected]
        if len(matches) != 1 or plan_enabled(matches[0].get("is_associated")) is None:
            msg = "The pet must have a known association state for this litter box"
            raise NottyApiError(msg)
        if plan_enabled(matches[0]["is_associated"]) is enabled:
            return rows
        await self.api.request(
            "POST",
            "/device/associate_pet",
            data={"user_device_id": identifier(device_id), "pet_id": selected, "associate": enabled},
        )
        return await self.associations(device_id)


class MemoApi:
    """Explicit pet-scoped text memos; no attachment upload or pet deletion."""

    def __init__(self, api: NottyApi) -> None:
        self.api = api
        self.pets = PetApi(api)

    async def list_memos(self, pet_id: str) -> list[JsonObject]:
        """List fresh memos for a pet in the account.

        Returns:
            Server memo records scoped to the selected pet.
        """
        await self.pets.profile(pet_id)
        return object_rows(await self.api.request("GET", f"/pet/memos/{identifier(pet_id)}"))

    async def detail(self, pet_id: str, memo_id: JsonValue) -> JsonObject:
        """Require fresh pet membership before retrieving a memo by its global ID.

        Returns:
            The matching memo detail.

        Raises:
            NottyApiError: If the ID belongs to another pet or detail is inconsistent.
        """
        selected = identifier(memo_id)
        rows = await self.list_memos(pet_id)
        if not any(identifier(row.get("memo_id")) == selected for row in rows):
            msg = "The memo does not belong to the selected pet"
            raise NottyApiError(msg)
        value = await self.api.request("GET", f"/pet/memo_detail/{selected}")
        if not isinstance(value, dict) or identifier(value.get("memo_id")) != selected:
            msg = "Memo detail identity mismatch"
            raise NottyApiError(msg)
        if value.get("pet_id") is not None and identifier(value["pet_id"]) != identifier(pet_id):
            msg = "Memo detail belongs to another pet"
            raise NottyApiError(msg)
        return value

    async def save(self, pet_id: str, changes: JsonObject, *, memo_id: JsonValue = None) -> JsonValue:
        """Create or edit an owner's memo using the app's complete text fields.

        Returns:
            Server acknowledgement; callers refresh the memo list after writing.
        """
        require_owner(await self.pets.profile(pet_id))
        create = memo_id is None
        current: JsonObject = {"remind": False, "expired": False} if create else await self.detail(pet_id, memo_id)
        payload = memo_payload(pet_id, current, changes, create=create)
        path = "/pet/add_memo" if create else "/pet/edit_memo"
        return await self.api.request("POST", path, data=payload)
