"""Explicit management of NOTTY litter-box fixed-clock cleaning plans."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.notty.api import (
    PLAN_ADD,
    PLAN_DELETE,
    PLAN_EDIT,
    PLAN_OPEN,
    JsonObject,
    JsonValue,
    NottyApiError,
)
from custom_components.notty.const import DOMAIN
from custom_components.notty.coordinator import NottyCoordinator
from custom_components.notty.entity import value_from_block
from custom_components.notty.validation import vol

SERVICE_LITTER_BOX_SCHEDULE = "litter_box_schedule"
OPERATION_LIST = "list"
OPERATION_ENABLE = "enable"
OPERATIONS = {"create": PLAN_ADD, "update": PLAN_EDIT, "enable": PLAN_OPEN, "disable": PLAN_OPEN, "delete": PLAN_DELETE}
OPERATION_FIELDS = {
    "list": set[str](),
    "create": {"time"},
    "update": {"plan_id", "time"},
    "enable": {"plan_id"},
    "disable": {"plan_id"},
    "delete": {"plan_id"},
}


def schedule_request(operation: str, fields: JsonObject) -> tuple[str, JsonObject]:
    """Translate an explicit HA operation without accepting unrelated settings.

    Returns:
        The APK operation and input fields to validate against a fresh list.

    Raises:
        NottyApiError: If operation fields are missing or irrelevant.
    """
    if operation not in OPERATION_FIELDS or set(fields) != OPERATION_FIELDS[operation]:
        msg = "Schedule fields do not match the requested operation"
        raise NottyApiError(msg)
    data = dict(fields)
    action = OPERATIONS.get(operation, OPERATION_LIST)
    if action == PLAN_OPEN:
        data["open"] = operation == OPERATION_ENABLE
    return action, data


def schedule_response(rows: list[JsonObject], device_time_zone: JsonValue) -> JsonObject:
    """Expose targeting fields and raw clocks, without guessing timezone conversion.

    Returns:
        Readback suitable for the HA action response, without unrelated backend fields.
    """
    plans: list[JsonValue] = [
        {key: row[key] for key in ("plan_id", "time", "open", "quantity", "plan_type_id") if key in row} for row in rows
    ]
    return {"plans": plans, "clock_basis": "notty_schedule_clock", "reported_device_time_zone": device_time_zone}


def register_schedule_service(
    hass: HomeAssistant, get_coordinator: Callable[[HomeAssistant, str], NottyCoordinator]
) -> None:
    """Register the explicitly invoked schedule service once per HA instance."""
    if hass.services.has_service(DOMAIN, SERVICE_LITTER_BOX_SCHEDULE):
        return

    async def handle(call: ServiceCall) -> JsonObject:
        """List or manage schedules on one configured physical litter box.

        Returns:
            Fresh plan readback with unconverted NOTTY clock values.

        Raises:
            HomeAssistantError: If a request is invalid or the API operation fails.
        """
        call_data = cast("JsonObject", call.data)
        device_id = str(call_data["user_device_id"])
        coordinator = get_coordinator(hass, device_id)
        device_zone = value_from_block(coordinator.data[device_id], "time_zone_iana")
        device_zone = device_zone if isinstance(device_zone, str) else None
        operation = str(call_data["operation"])
        fields = {key: value for key, value in call_data.items() if key not in {"user_device_id", "operation"}}
        try:
            action, data = schedule_request(operation, fields)
            if operation != OPERATION_LIST:
                await coordinator.api.manage_litter_plan(device_id, action, data)
                await coordinator.async_request_refresh()
            rows = await coordinator.api.litter_plans(device_id)
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        return schedule_response(rows, device_zone)

    device_id_validator: vol.Coerce[str] = vol.Coerce(str)
    schema: dict[object, object] = {
        vol.Required("user_device_id"): device_id_validator,
        vol.Required("operation"): vol.In(OPERATION_FIELDS),
        vol.Optional("plan_id"): vol.Any(str, int),
        vol.Optional("time"): str,
    }
    hass.services.async_register(
        DOMAIN,
        SERVICE_LITTER_BOX_SCHEDULE,
        handle,
        schema=vol.Schema(schema),
        supports_response=SupportsResponse.OPTIONAL,
    )
