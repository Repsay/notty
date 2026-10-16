"""Timezone selection contracts, readback and HA action lifecycle without writes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.notty.api import (
    JsonObject,
    JsonValue,
    NottyApi,
    NottyApiError,
    timezone_catalog,
    timezone_payload,
)
from custom_components.notty.device_timezone import change_with_readback, timezone_change_fields, timezone_snapshot
from tests.test_lifecycle import setup

WINDOWS_ID = "W. Europe Standard Time"
LOCAL_ZONE = "Europe/Amsterdam"
BOX_ID = "123"
CATALOG: list[JsonValue] = [
    {"id": WINDOWS_ID, "display_name": "(UTC+01:00) Amsterdam, Berlin", "offset": "01:00:00"},
    {"id": "UTC", "display_name": "(UTC) Coordinated Universal Time", "offset": "00:00:00"},
]
FIELDS: JsonObject = {"catalog_id": WINDOWS_ID, "confirm_schedule_change": True}
INFO: JsonObject = {
    "user_device_id": 123,
    "time_zone_iana": LOCAL_ZONE,
    "time_zone_windows": "UTC",
    "dnd_begin_time": "22:00",
    "dnd_end_time": "07:00",
    "switch_dnd": 1,
    "mode": 1,
}
SERVICE = "device_time_zone"
READBACK_FAILED = "write_acknowledged_readback_failed"
UNCHANGED = "unchanged"
TWO_READS = 2
ACKNOWLEDGED = "write_acknowledged_verify_in_app"


@pytest.mark.parametrize("value", [None, {}, [], [None], [{"id": 1}], CATALOG + CATALOG])
def test_catalog_rejects_invalid_or_duplicate_records(value: JsonValue) -> None:
    """Never manufacture timezone choices from malformed data."""
    with pytest.raises(NottyApiError):
        timezone_catalog(value)


@pytest.mark.parametrize("field", ["id", "display_name", "offset"])
@pytest.mark.parametrize("value", [None, 1, "", " ", "bad\nvalue"])
def test_catalog_string_fields(field: str, value: JsonValue) -> None:
    """Catalog values must be usable strings; no silent coercion or trimming."""
    row = dict(CATALOG[0])
    row[field] = value
    with pytest.raises(NottyApiError):
        timezone_catalog([row])


def test_exact_windows_id_is_serialized_in_misnamed_iana_field() -> None:
    """The view passes catalog[id], not an IANA mapping or fixed offset."""
    rows = timezone_catalog(CATALOG)
    assert timezone_payload(BOX_ID, WINDOWS_ID, rows) == {"user_device_id": 123, "time_zone_iana": WINDOWS_ID}
    for invalid in (LOCAL_ZONE, "01:00:00", "1", "unknown", f" {WINDOWS_ID}"):
        with pytest.raises(NottyApiError):
            timezone_payload(BOX_ID, invalid, rows)


@pytest.mark.parametrize("device_id", ["0", "-1", "box-1", "\uff11\uff12\uff13", "123/other", ""])
def test_invalid_physical_ids(device_id: str) -> None:
    """Never serialize pet IDs or URL/path fragments as physical IDs."""
    with pytest.raises(NottyApiError):
        timezone_payload(device_id, WINDOWS_ID, timezone_catalog(CATALOG))


async def test_fresh_catalog_and_exact_api_payload() -> None:
    """Every write checks current membership and makes a single exact POST."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(side_effect=[CATALOG, {}])
    await api.change_time_zone(BOX_ID, WINDOWS_ID)
    assert api.request.await_args_list[0].args == ("GET", "/entity/get_time_zones")
    api.request.assert_awaited_with(
        "POST", "/device/change_time_zone", data={"user_device_id": 123, "time_zone_iana": WINDOWS_ID}
    )
    assert api.request.await_count == TWO_READS


async def test_unsupported_choice_never_writes() -> None:
    """A valid IANA name is not a supported Windows catalog identifier."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock(return_value=CATALOG)
    with pytest.raises(NottyApiError):
        await api.change_time_zone(BOX_ID, LOCAL_ZONE)
    api.request.assert_awaited_once_with("GET", "/entity/get_time_zones")


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"catalog_id": WINDOWS_ID},
        {**FIELDS, "confirm_schedule_change": 1},
        {**FIELDS, "confirm_schedule_change": False},
        {**FIELDS, "device_id": 999},
    ],
)
def test_changes_require_explicit_schedule_acknowledgement(fields: JsonObject) -> None:
    """Extra targeting or implicit truthy values cannot authorize a change."""
    with pytest.raises(NottyApiError):
        timezone_change_fields(fields)


async def test_changed_settings_are_reported_without_automatic_restore() -> None:
    """One write followed by readback exposes drift without a second write."""
    api = MagicMock(spec=NottyApi)
    api.litter_info.side_effect = [INFO, {**INFO, "time_zone_iana": LOCAL_ZONE, "dnd_begin_time": "23:00"}]
    api.request.return_value = [{"plan_id": 1, "time": "06:30", "open": True}]
    result = await change_with_readback(api, BOX_ID, FIELDS)
    assert result["status"] == ACKNOWLEDGED
    assert result["changed_schedule_fields"] == ["settings"]
    api.change_time_zone.assert_awaited_once_with(BOX_ID, WINDOWS_ID)
    assert api.request.await_count == TWO_READS


async def test_known_windows_same_state_is_noop() -> None:
    """A directly reported Windows ID can establish a safe no-op."""
    api = MagicMock(spec=NottyApi)
    api.litter_info.return_value = {**INFO, "time_zone_windows": WINDOWS_ID}
    api.request.return_value = []
    result = await change_with_readback(api, BOX_ID, FIELDS)
    assert result["status"] == UNCHANGED
    api.change_time_zone.assert_not_awaited()


async def test_failure_after_acknowledged_write_is_distinguished() -> None:
    """A failed read must not encourage an automatic repeat of an accepted write."""
    api = MagicMock(spec=NottyApi)
    api.litter_info.side_effect = [INFO, NottyApiError("offline")]
    api.request.return_value = []
    result = await change_with_readback(api, BOX_ID, FIELDS)
    assert result["status"] == READBACK_FAILED
    api.change_time_zone.assert_awaited_once()


async def test_unreadable_plans_block_changes() -> None:
    """No timezone write without the scheduling baseline."""
    api = MagicMock(spec=NottyApi)
    api.litter_info.return_value = INFO
    api.request.return_value = None
    with pytest.raises(NottyApiError):
        await change_with_readback(api, BOX_ID, FIELDS)
    api.change_time_zone.assert_not_awaited()


async def test_snapshot_rejects_identity_mismatch() -> None:
    """Cross-device metadata cannot authorize changing the selected device."""
    api = MagicMock(spec=NottyApi)
    api.litter_info.return_value = {**INFO, "user_device_id": 999}
    with pytest.raises(NottyApiError):
        await timezone_snapshot(api, BOX_ID)
    api.request.assert_not_awaited()


async def test_generic_action_cannot_bypass_catalog() -> None:
    """The old unchecked endpoint map cannot bypass validated membership."""
    api = NottyApi(MagicMock())
    api.request = AsyncMock()
    with pytest.raises(NottyApiError):
        await api.litter_action(BOX_ID, "change_time_zone", {"time_zone_iana": LOCAL_ZONE})
    api.request.assert_not_awaited()


async def test_ha_read_action_lifecycle(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Expose separate clocks and server options without writes or background polling."""
    runtime_api.devices.return_value[0]["user_device_id"] = BOX_ID
    runtime_api.device_info.return_value.update(INFO)
    runtime_api.litter_info.return_value = INFO
    runtime_api.request.return_value = []
    runtime_api.time_zones.return_value = timezone_catalog(CATALOG)
    entry = await setup(hass)
    runtime_api.time_zones.assert_not_awaited()
    response = await hass.services.async_call(
        "notty", SERVICE, {"user_device_id": BOX_ID, "operation": "list"}, blocking=True, return_response=True
    )
    assert response["catalog"] == CATALOG
    assert response["current"]["reported_iana"] == LOCAL_ZONE
    runtime_api.change_time_zone.assert_not_awaited()
    await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("notty", SERVICE)


async def test_ha_rejects_unknown_device_and_missing_confirmation(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Service validation blocks unknown physical targets and implicit writes."""
    runtime_api.devices.return_value[0]["user_device_id"] = BOX_ID
    await setup(hass)
    for data in (
        {"user_device_id": "unknown", "operation": "list"},
        {"user_device_id": BOX_ID, "operation": "change", "catalog_id": WINDOWS_ID},
    ):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call("notty", SERVICE, data, blocking=True)
    runtime_api.change_time_zone.assert_not_awaited()
