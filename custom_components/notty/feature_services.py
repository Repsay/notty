"""Native HA actions for pet editing, associations, memos and account preferences."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.notty.api import JsonObject, JsonValue, NottyApiError
from custom_components.notty.const import DOMAIN
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.device_features import NotificationApi, clear_statistics, owned_litter
from custom_components.notty.feature_contracts import identifier
from custom_components.notty.pet_api import MemoApi, PetApi
from custom_components.notty.validation import vol

SERVICE_PET_PROFILE = "pet_profile"
SERVICE_PET_ASSOCIATION = "pet_association"
SERVICE_PET_MEMO = "pet_memo"
SERVICE_NOTIFICATIONS = "notification_preferences"
SERVICE_CLEAR_STATISTICS = "clear_statistics"
FEATURE_SERVICES = (
    SERVICE_PET_PROFILE,
    SERVICE_PET_ASSOCIATION,
    SERVICE_PET_MEMO,
    SERVICE_NOTIFICATIONS,
    SERVICE_CLEAR_STATISTICS,
)
OP_LIST = "list"
OP_GET = "get"
OP_BREEDS = "breeds"
OP_CREATE = "create"
OP_UPDATE = "update"
OP_DETAIL = "detail"
OP_ASSOCIATE = "associate"
OP_BLOCK = "block"
OPERATION_FIELDS = {
    SERVICE_PET_PROFILE: {OP_GET: set[str](), OP_BREEDS: set[str](), OP_UPDATE: {"changes"}},
    SERVICE_PET_ASSOCIATION: {OP_LIST: set[str](), OP_ASSOCIATE: {"pet_id"}, "disassociate": {"pet_id"}},
    SERVICE_PET_MEMO: {
        OP_LIST: set[str](),
        OP_DETAIL: {"memo_id"},
        OP_CREATE: {"changes"},
        OP_UPDATE: {"memo_id", "changes"},
    },
    SERVICE_NOTIFICATIONS: {OP_LIST: set[str](), OP_BLOCK: {"message_type_id"}, "unblock": {"message_type_id"}},
}

type ResolveCoordinator = Callable[[HomeAssistant, str], NottyCoordinator]


def profile_response(value: JsonObject) -> JsonObject:
    """Expose useful profile fields without backend URLs or unrelated health data.

    Returns:
        Supported profile values, ownership and current device bindings.
    """
    return {
        key: value[key]
        for key in (
            "name",
            "birthday",
            "sex",
            "is_sterilization",
            "breed_id",
            "breed_name",
            "weight",
            "weight_unit",
            "pet_id",
            "is_owner",
            "pet_devices",
        )
        if key in value
    }


def _changes(data: JsonObject) -> JsonObject:
    value = data.get("changes", {})
    if isinstance(value, dict):
        return value
    msg = "Changes must be an object of supported fields"
    raise NottyApiError(msg)


class FeatureHandlers:
    """Resolve loaded accounts and return readback after explicit service writes."""

    def __init__(self, hass: HomeAssistant, physical: ResolveCoordinator, pet: ResolveCoordinator) -> None:
        self.hass, self.physical, self.pet = hass, physical, pet

    async def profile(self, data: JsonObject) -> JsonObject:
        """Read or edit an existing pet, or list its server breed choices.

        Returns:
            Selected profile or breed readback.
        """
        pet_id = str(identifier(data["pet_id"]))
        coordinator = self.pet(self.hass, pet_id)
        api = PetApi(coordinator.api)
        operation = data["operation"]
        if operation == OP_BREEDS:
            return {"breeds": cast("JsonValue", await api.breeds())}
        if operation == OP_GET:
            return {"profile": profile_response(await api.profile(pet_id))}
        result = await api.update(pet_id, _changes(data))
        await coordinator.async_request_refresh()
        return {"profile": profile_response(result), "status": "readback_after_write"}

    async def association(self, data: JsonObject) -> JsonObject:
        """List or change one pet-to-litter-box association.

        Returns:
            Fresh associations; unrelated bindings are never submitted.
        """
        device_id = str(identifier(data["user_device_id"]))
        coordinator = self.physical(self.hass, device_id)
        api = PetApi(coordinator.api)
        operation = data["operation"]
        if operation == OP_LIST:
            rows = await api.associations(device_id)
        else:
            await owned_litter(coordinator.api, device_id)
            rows = await api.associate(
                device_id, str(identifier(data.get("pet_id"))), enabled=operation == OP_ASSOCIATE
            )
            await coordinator.async_request_refresh()
        return {"pets": cast("JsonValue", rows)}

    async def memo(self, data: JsonObject) -> JsonObject:
        """List/read/create/edit one selected pet's text memos.

        Returns:
            Memo details or fresh list readback after a write.

        Raises:
            NottyApiError: If a read-only memo listing fails.
        """
        pet_id = str(identifier(data["pet_id"]))
        coordinator = self.pet(self.hass, pet_id)
        api = MemoApi(coordinator.api)
        operation = data["operation"]
        if operation == OP_DETAIL:
            return {"memo": await api.detail(pet_id, data.get("memo_id"))}
        if operation in {OP_CREATE, OP_UPDATE}:
            memo_id = identifier(data.get("memo_id")) if operation == OP_UPDATE else None
            await api.save(pet_id, _changes(data), memo_id=memo_id)
            await coordinator.async_request_refresh()
        try:
            rows = await api.list_memos(pet_id)
        except NottyApiError:
            if operation == OP_LIST:
                raise
            return {"status": "write_acknowledged_readback_failed", "clock_basis": "notty_memo_wall_clock"}
        return {"memos": cast("JsonValue", rows), "clock_basis": "notty_memo_wall_clock"}

    async def notifications(self, data: JsonObject) -> JsonObject:
        """Operate on account preferences, using a device only to select its account.

        Returns:
            Current account-wide litter-box notification categories.
        """
        coordinator = self.physical(self.hass, str(identifier(data["user_device_id"])))
        api = NotificationApi(coordinator.api)
        if data["operation"] == OP_LIST:
            rows = await api.categories()
        else:
            rows = await api.set_blocked(data.get("message_type_id"), blocked=data["operation"] == OP_BLOCK)
        return {"scope": "notty_account_litter_box_categories", "categories": cast("JsonValue", rows)}

    async def statistics(self, data: JsonObject) -> JsonObject:
        """Clear statistics only after explicit confirmation of irreversible deletion.

        Returns:
            Server acknowledgement, followed by coordinator sensor refresh.
        """
        device_id = str(identifier(data["user_device_id"]))
        coordinator = self.physical(self.hass, device_id)
        result = await clear_statistics(coordinator.api, device_id, confirmed=data.get("confirm_irreversible") is True)
        await coordinator.async_request_refresh()
        return result


def _validate_operation(service: str, data: JsonObject) -> None:
    if service == SERVICE_CLEAR_STATISTICS:
        return
    operation = str(data["operation"])
    target = "pet_id" if service in {SERVICE_PET_PROFILE, SERVICE_PET_MEMO} else "user_device_id"
    expected = {target, "operation"} | OPERATION_FIELDS[service][operation]
    if set(data) != expected:
        msg = "Fields do not match the selected NOTTY operation"
        raise NottyApiError(msg)


def _wrap(
    service: str, handler: Callable[[JsonObject], Awaitable[JsonObject]]
) -> Callable[[ServiceCall], Coroutine[None, None, JsonObject]]:
    async def handle(call: ServiceCall) -> JsonObject:
        """Translate API validation errors to native HA action errors.

        Returns:
            The selected operation's response.

        Raises:
            HomeAssistantError: If validation or the API request fails.
        """
        try:
            data = cast("JsonObject", call.data)
            _validate_operation(service, data)
            return await handler(data)
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc

    return handle


def register_feature_services(hass: HomeAssistant, physical: ResolveCoordinator, pet: ResolveCoordinator) -> None:
    """Expose native action schemas and responses for the remaining litter/pet features."""
    handlers = FeatureHandlers(hass, physical, pet)
    id_value = vol.Any(str, int)
    changes: dict[object, object] = {vol.Optional("changes"): cast("type[dict[str, object]]", dict)}
    schemas: dict[str, tuple[Callable[[JsonObject], Awaitable[JsonObject]], dict[object, object]]] = {
        SERVICE_PET_PROFILE: (
            handlers.profile,
            {
                vol.Required("pet_id"): id_value,
                vol.Required("operation"): vol.In(("get", "update", "breeds")),
                **changes,
            },
        ),
        SERVICE_PET_ASSOCIATION: (
            handlers.association,
            {
                vol.Required("user_device_id"): id_value,
                vol.Required("operation"): vol.In(("list", "associate", "disassociate")),
                vol.Optional("pet_id"): id_value,
            },
        ),
        SERVICE_PET_MEMO: (
            handlers.memo,
            {
                vol.Required("pet_id"): id_value,
                vol.Required("operation"): vol.In(("list", "detail", "create", "update")),
                vol.Optional("memo_id"): id_value,
                **changes,
            },
        ),
        SERVICE_NOTIFICATIONS: (
            handlers.notifications,
            {
                vol.Required("user_device_id"): id_value,
                vol.Required("operation"): vol.In(("list", "block", "unblock")),
                vol.Optional("message_type_id"): id_value,
            },
        ),
        SERVICE_CLEAR_STATISTICS: (
            handlers.statistics,
            {vol.Required("user_device_id"): id_value, vol.Required("confirm_irreversible"): bool},
        ),
    }
    for service, (handler, schema) in schemas.items():
        if not hass.services.has_service(DOMAIN, service):
            hass.services.async_register(
                DOMAIN,
                service,
                _wrap(service, handler),
                schema=vol.Schema(schema),
                supports_response=SupportsResponse.OPTIONAL,
            )
