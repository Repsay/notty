"""Explicit device timezone selection with separate clock context and readback."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.notty.api import (
    JsonObject,
    JsonValue,
    NottyApi,
    NottyApiError,
    dnd_local_time,
    dnd_payload,
    validated_iana_zone,
)
from custom_components.notty.const import DOMAIN
from custom_components.notty.coordinator import NOTTY_SERVER_TIME_ZONE, NottyCoordinator
from custom_components.notty.validation import vol

SERVICE_DEVICE_TIME_ZONE = "device_time_zone"
OPERATION_LIST = "list"
SCHEDULE_FIELDS = ("switch_dnd", "dnd_begin_time", "dnd_end_time", "led", "mode", "auto_delay")


async def timezone_snapshot(api: NottyApi, device_id: str) -> JsonObject:
    """Read settings and plans without guessing their clock basis.

    Returns:
        Current scheduling fields and separately reported IANA/Windows zones.

    Raises:
        NottyApiError: If identity or readback cannot be established.
    """
    if not device_id.isascii() or not device_id.isdecimal() or int(device_id) <= 0:
        msg = "Timezone readback requires a positive numeric physical device ID"
        raise NottyApiError(msg)
    info = await api.litter_info(device_id)
    if str(info.get("user_device_id")) != device_id:
        msg = "Timezone readback requires a matching physical device ID"
        raise NottyApiError(msg)
    plans = await api.request("GET", f"/device/litter_box/plans/{device_id}")
    if not isinstance(plans, list) or any(not isinstance(row, dict) for row in plans):
        msg = "Timezone checks require readable cleaning plans"
        raise NottyApiError(msg)
    return {
        "reported_iana": info.get("time_zone_iana"),
        "reported_windows": info.get("time_zone_windows"),
        "settings": {key: info.get(key) for key in SCHEDULE_FIELDS},
        "plans": plans,
    }


def timezone_change_fields(fields: JsonObject) -> str:
    """Require an explicit choice and acknowledgement of schedule reinterpretation.

    Returns:
        The exact selected server ID.

    Raises:
        NottyApiError: If fields are missing, extra or invalid.
    """
    required = {"catalog_id", "iana_time_zone", "confirm_schedule_change"}
    if not required <= fields.keys() or fields.keys() - required - {"preserve_dnd_local_times"}:
        msg = "Timezone changes require catalog_id, iana_time_zone and confirm_schedule_change: true"
        raise NottyApiError(msg)
    if (
        fields.get("confirm_schedule_change") is not True
        or type(fields.get("preserve_dnd_local_times", False)) is not bool
    ):
        msg = "Timezone acknowledgement and preservation must be Booleans"
        raise NottyApiError(msg)
    identifier = fields["catalog_id"]
    if not isinstance(identifier, str) or not identifier.strip():
        msg = "Choose an exact string ID from the NOTTY catalog"
        raise NottyApiError(msg)
    zone = fields["iana_time_zone"]
    if not isinstance(zone, str):
        msg = "Choose an explicit IANA timezone name"
        raise NottyApiError(msg)
    validated_iana_zone(zone)
    return identifier


def _local_dnd(snapshot: JsonObject) -> JsonObject:
    settings, zone = snapshot.get("settings"), snapshot.get("reported_iana")
    if not isinstance(settings, dict) or not isinstance(zone, str):
        msg = "DND preservation needs readable settings and a valid device IANA zone"
        raise NottyApiError(msg)
    dnd_payload({**settings, "time_zone_iana": zone})
    return {
        key: dnd_local_time(settings.get(key), zone).strftime("%H:%M") for key in ("dnd_begin_time", "dnd_end_time")
    }


async def _preserve_dnd(api: NottyApi, device_id: str, before: JsonObject, after: JsonObject) -> JsonObject:
    settings = before.get("settings")
    if not isinstance(settings, dict):
        msg = "DND preservation requires the original settings"
        raise NottyApiError(msg)
    local = _local_dnd(before)
    current = {**settings, "time_zone_iana": after.get("reported_iana")}
    # The API can shift its raw DND fields on timezone changes. Preserve the
    # owner's original local wall clocks, flags and LED with one explicit write.
    await api.litter_action(
        device_id,
        "set_dnd",
        dnd_payload(current, dnd_begin_time=local["dnd_begin_time"], dnd_end_time=local["dnd_end_time"]),
    )
    return await timezone_snapshot(api, device_id)


async def change_with_readback(api: NottyApi, device_id: str, fields: JsonObject) -> JsonObject:
    """Change the timezone once and optionally preserve DND, without replay or rollback.

    Returns:
        Before/after readback. Matching fields do not prove unchanged firing times.
    """
    identifier = timezone_change_fields(fields)
    zone = str(fields["iana_time_zone"])
    preserve = fields.get("preserve_dnd_local_times") is True
    before = await timezone_snapshot(api, device_id)
    if preserve:
        _local_dnd(before)
    if before["reported_windows"] == identifier and before["reported_iana"] == zone:
        return {"status": "unchanged", "before": before, "after": before}
    await api.change_time_zone(device_id, identifier, iana_time_zone=zone)
    try:
        after = await timezone_snapshot(api, device_id)
    except NottyApiError:
        return {"status": "write_acknowledged_readback_failed", "before": before}
    if after["reported_iana"] != zone or after["reported_windows"] != identifier:
        return {"status": "timezone_readback_mismatch", "before": before, "after": after}
    preservation: str = "not_requested"
    if preserve:
        try:
            after = await _preserve_dnd(api, device_id, before, after)
            preservation = "local_clocks_match" if _local_dnd(before) == _local_dnd(after) else "local_clock_mismatch"
        except NottyApiError:
            return {"status": "timezone_changed_dnd_preservation_failed", "before": before, "after": after}
    changed: list[JsonValue] = [key for key in ("settings", "plans") if before[key] != after[key]]
    return {
        "status": "write_acknowledged_verify_in_app",
        "requested_catalog_id": identifier,
        "requested_iana_time_zone": zone,
        "dnd_preservation": preservation,
        "before": before,
        "after": after,
        "changed_schedule_fields": changed,
    }


def _list_fields(fields: JsonObject) -> None:
    if fields:
        msg = "Timezone listing accepts no write fields"
        raise NottyApiError(msg)


def register_timezone_service(
    hass: HomeAssistant, get_coordinator: Callable[[HomeAssistant, str], NottyCoordinator]
) -> None:
    """Register a catalog/readback action and an explicit timezone change operation."""
    if hass.services.has_service(DOMAIN, SERVICE_DEVICE_TIME_ZONE):
        return

    async def handle(call: ServiceCall) -> JsonObject:
        """Handle one owner-selected timezone operation.

        Returns:
            Catalog and separate clock context, or a before/after change report.

        Raises:
            HomeAssistantError: If validation or a required API read/write fails.
        """
        data = cast("JsonObject", call.data)
        device_id = str(data["user_device_id"])
        coordinator = get_coordinator(hass, device_id)
        fields = {key: value for key, value in data.items() if key not in {"user_device_id", "operation"}}
        try:
            if data["operation"] == OPERATION_LIST:
                _list_fields(fields)
                return {
                    "catalog": cast("JsonValue", await coordinator.api.time_zones()),
                    "current": await timezone_snapshot(coordinator.api, device_id),
                    "home_assistant_time_zone": hass.config.time_zone,
                    "assumed_server_event_time_zone": NOTTY_SERVER_TIME_ZONE,
                    "catalog_offset_basis": "standard_time_not_current_dst_offset",
                }
            result = await change_with_readback(coordinator.api, device_id, fields)
        except NottyApiError as exc:
            raise HomeAssistantError(str(exc)) from exc
        await coordinator.async_request_refresh()
        return result

    validator: vol.Coerce[str] = vol.Coerce(str)
    schema: dict[object, object] = {
        vol.Required("user_device_id"): validator,
        vol.Required("operation"): vol.In(("list", "change")),
        vol.Optional("catalog_id"): str,
        vol.Optional("iana_time_zone"): str,
        vol.Optional("preserve_dnd_local_times"): bool,
        vol.Optional("confirm_schedule_change"): bool,
    }
    hass.services.async_register(
        DOMAIN, SERVICE_DEVICE_TIME_ZONE, handle, schema=vol.Schema(schema), supports_response=SupportsResponse.OPTIONAL
    )
