"""Read-only NOTTY timezone diagnostics and catalog-schema verification."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
import pytest

from custom_components.notty.coordinator import NOTTY_SERVER_TIME_ZONE
from custom_components.notty.sensor import FIELD_DEVICE_TIME_ZONE, sensor_keys, timezone_context
from scripts.probe_timezones import (
    MAX_MATCHES,
    TIME_ZONE_CATALOG_PATH,
    catalog_entries,
    catalog_report,
    collect_catalog,
    device_timezone_fields,
    inspect_device_timezone,
)
from tests.test_lifecycle import setup

LOCAL_ZONE = "Europe/Amsterdam"
OFFSET_KEY = "device_utc_offset_minutes"
SAMPLE_CATALOG_SENTINEL = "private-token"
CATALOG_DEVICE_ID = "52963"
CATALOG_LIST_PATH = "$[]"
EXPECTED_CATALOG_COUNT = 2
EXPECTED_AMSTERDAM_CEST_OFFSET = 120
EXPECTED_AMSTERDAM_CET_OFFSET = 60
EXPECTED_NEW_YORK_EDT_OFFSET = -240
EXPECTED_NEW_YORK_EST_OFFSET = -300
EXPECTED_MINUS_SIX_HOURS = -360
EXPECTED_MINUS_FIVE_HOURS = -300


@pytest.mark.parametrize(
    ("at", "device_offset", "ha_offset", "difference"),
    [
        (
            datetime(2026, 10, 16, 12, tzinfo=UTC),
            EXPECTED_NEW_YORK_EDT_OFFSET,
            EXPECTED_AMSTERDAM_CEST_OFFSET,
            EXPECTED_MINUS_SIX_HOURS,
        ),
        (
            datetime(2026, 10, 26, 12, tzinfo=UTC),
            EXPECTED_NEW_YORK_EDT_OFFSET,
            EXPECTED_AMSTERDAM_CET_OFFSET,
            EXPECTED_MINUS_FIVE_HOURS,
        ),
        (
            datetime(2026, 11, 16, 12, tzinfo=UTC),
            EXPECTED_NEW_YORK_EST_OFFSET,
            EXPECTED_AMSTERDAM_CET_OFFSET,
            EXPECTED_MINUS_SIX_HOURS,
        ),
    ],
)
def test_timezone_context_accounts_for_independent_dst_transitions(
    at: datetime, device_offset: int, ha_offset: int, difference: int
) -> None:
    """NOTTY and HA can transition on different dates."""
    context = timezone_context("America/New_York", "Europe/Amsterdam", at=at)
    assert context["device_iana_valid"] is True
    assert context["device_utc_offset_minutes"] == device_offset
    assert context["home_assistant_utc_offset_minutes"] == ha_offset
    assert context["device_minus_ha_offset_minutes"] == difference
    assert context["server_clock_assumption"] == NOTTY_SERVER_TIME_ZONE


@pytest.mark.parametrize("invalid", [None, False, 8, "", "Not/ARealZone"])
def test_unknown_device_timezone_is_not_guessed(invalid: object) -> None:
    """Invalid NOTTY values never silently become the HA timezone."""
    context = timezone_context(invalid, LOCAL_ZONE)
    assert context["device_iana_valid"] is False
    assert OFFSET_KEY not in context
    assert context["home_assistant_time_zone"] == LOCAL_ZONE


async def test_existing_timezone_sensor_displays_device_vs_ha(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Keep the existing sensor identity and expose diagnostic offsets."""
    hass.config.time_zone = LOCAL_ZONE
    runtime_api.device_info.return_value[FIELD_DEVICE_TIME_ZONE] = LOCAL_ZONE
    await setup(hass)
    state = hass.states.get("sensor.test_box_time_zone_iana")
    assert state is not None
    assert state.state == LOCAL_ZONE
    assert state.attributes["home_assistant_time_zone"] == LOCAL_ZONE
    assert state.attributes["server_clock_assumption"] == NOTTY_SERVER_TIME_ZONE
    assert state.attributes["device_iana_valid"] is True
    assert state.attributes["device_minus_ha_offset_minutes"] == 0
    runtime_api.litter_action.assert_not_awaited()


def test_timezone_field_still_uses_generic_discovery() -> None:
    """The read-only timezone entity is created only when NOTTY reports it."""
    empty = {"device": {"alias": "box"}, "info": {"today_clean_count": 1}}
    found = {"device": {"time_zone_iana": "Europe/Amsterdam"}, "info": {"today_clean_count": 1}}
    assert FIELD_DEVICE_TIME_ZONE not in sensor_keys(empty)
    assert FIELD_DEVICE_TIME_ZONE in sensor_keys(found)


def test_catalog_inventory_does_not_include_response_values() -> None:
    """A shareable report must not leak catalog IDs, tokens or private values."""
    response = [
        {"id": CATALOG_DEVICE_ID, "display_name": LOCAL_ZONE, "offset": "UTC+02:00", "secret": SAMPLE_CATALOG_SENTINEL},
        {"id": "92001", "display_name": "America/New_York", "offset": "UTC-04:00"},
    ]
    result = catalog_report(response)
    text = json.dumps(result)
    assert TIME_ZONE_CATALOG_PATH in text
    assert SAMPLE_CATALOG_SENTINEL not in text
    assert LOCAL_ZONE not in text
    assert CATALOG_DEVICE_ID not in text
    assert CATALOG_LIST_PATH in text


def test_catalog_lookup_reveals_only_matching_server_provided_strings() -> None:
    """The catalog ID is an opaque string; never infer an IANA identifier."""
    response = [
        {
            "id": "W. Europe Standard Time",
            "display_name": "(UTC+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
            "offset": "01:00:00",
            "ignored": SAMPLE_CATALOG_SENTINEL,
        },
        {"id": "Eastern Standard Time", "display_name": "(UTC-05:00) Eastern Time", "offset": "-05:00:00"},
    ]
    result = catalog_report(response, find="Amsterdam")
    assert result["entry_count"] == EXPECTED_CATALOG_COUNT
    assert result["match_count"] == 1
    assert result["matches"] == [
        {
            "id": "W. Europe Standard Time",
            "display_name": "(UTC+01:00) Amsterdam, Berlin, Bern, Rome, Stockholm, Vienna",
            "offset": "01:00:00",
        }
    ]
    assert result["matches_truncated"] is False
    assert SAMPLE_CATALOG_SENTINEL not in json.dumps(result)


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        ({}, TypeError),
        (None, TypeError),
        (["bad-entry"], TypeError),
        ([{"id": 3, "display_name": "Amsterdam", "offset": "+02:00"}], TypeError),
        ([{"id": "one", "display_name": None, "offset": "+02:00"}], TypeError),
        ([{"id": "one", "display_name": "Amsterdam", "offset": ""}], ValueError),
        (
            [
                {"id": "duplicate", "display_name": "Amsterdam", "offset": "+02:00"},
                {"id": "duplicate", "display_name": "Another", "offset": "+03:00"},
            ],
            ValueError,
        ),
    ],
)
def test_catalog_rejects_malformed_entries(response: object, error_type: type[Exception]) -> None:
    """No device timezone options are guessed from malformed responses."""
    with pytest.raises(error_type, match="Timezone catalog"):
        catalog_entries(response)


def test_catalog_search_requires_specific_filter() -> None:
    """A short search should not accidentally reveal the entire catalog."""
    with pytest.raises(ValueError, match="three characters"):
        catalog_report([{"id": "X", "display_name": "Amsterdam", "offset": "+02:00"}], find="a")


def test_catalog_match_output_bounded() -> None:
    """A broad match is limited to ten results, not the full catalog."""
    catalog = [{"id": f"zone-{n}", "display_name": f"Europe Zone {n}", "offset": "+01:00"} for n in range(16)]
    result = catalog_report(catalog, find="Zone")
    assert result["match_count"] == len(catalog)
    assert result["matches_truncated"] is True
    assert len(result["matches"]) == MAX_MATCHES


def test_device_timezone_fields_never_exposes_identifiers() -> None:
    """Only known timezone strings are copied into the shareable report."""
    result = device_timezone_fields({
        "user_device_id": CATALOG_DEVICE_ID,
        "access_token": SAMPLE_CATALOG_SENTINEL,
        "time_zone_iana": LOCAL_ZONE,
        "time_zone_id": "W. Europe Standard Time",
        "timezone": 3,
    })
    assert result == {"time_zone_iana": LOCAL_ZONE, "time_zone_id": "W. Europe Standard Time"}
    assert CATALOG_DEVICE_ID not in json.dumps(result)
    assert SAMPLE_CATALOG_SENTINEL not in json.dumps(result)


async def test_device_timezone_inspection_uses_only_list_and_info_reads() -> None:
    """Distinguish the selection catalog's Windows ID from device IANA fields."""
    api = MagicMock()
    api.devices = AsyncMock(
        return_value=[
            {"user_device_id": CATALOG_DEVICE_ID, "time_zone_iana": LOCAL_ZONE, "alias": SAMPLE_CATALOG_SENTINEL}
        ]
    )
    api.litter_info = AsyncMock(
        return_value={"user_device_id": CATALOG_DEVICE_ID, "time_zone_iana": LOCAL_ZONE, "status_id": 1}
    )
    result = await inspect_device_timezone(api, CATALOG_DEVICE_ID)
    assert result == {
        "device_listing": {"time_zone_iana": LOCAL_ZONE},
        "litter_box_info": {"time_zone_iana": LOCAL_ZONE},
    }
    api.litter_info.assert_awaited_once_with(CATALOG_DEVICE_ID)
    api.litter_action.assert_not_called()
    assert SAMPLE_CATALOG_SENTINEL not in json.dumps(result)
    assert CATALOG_DEVICE_ID not in json.dumps(result)


async def test_timezone_inspection_rejects_unlisted_device_before_info_read() -> None:
    """Refuse reads on devices absent from the user's account discovery."""
    api = MagicMock()
    api.devices = AsyncMock(return_value=[{"user_device_id": "different-device"}])
    api.litter_info = AsyncMock()
    with pytest.raises(ValueError, match="does not match"):
        await inspect_device_timezone(api, CATALOG_DEVICE_ID)
    api.litter_info.assert_not_awaited()


async def test_catalog_probe_sends_only_one_read_request() -> None:
    """Never use change_time_zone when discovering server-supported IDs."""
    api = MagicMock()
    api.request = AsyncMock(return_value={"list": []})
    result = await collect_catalog(api)
    assert result == {"list": []}
    api.request.assert_awaited_once_with("GET", TIME_ZONE_CATALOG_PATH)
    api.litter_action.assert_not_called()
