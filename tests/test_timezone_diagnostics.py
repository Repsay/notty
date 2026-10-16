"""Read-only NOTTY timezone diagnostics and catalog-schema verification."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
import pytest

from custom_components.notty.coordinator import NOTTY_SERVER_TIME_ZONE
from custom_components.notty.sensor import sensor_keys, timezone_context
from scripts.probe_timezones import TIME_ZONE_CATALOG_PATH, catalog_report, collect_catalog
from tests.test_lifecycle import setup

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
    context = timezone_context(invalid, "Europe/Amsterdam")
    assert context["device_iana_valid"] is False
    assert "device_utc_offset_minutes" not in context
    assert context["home_assistant_time_zone"] == "Europe/Amsterdam"


async def test_existing_timezone_sensor_displays_device_vs_ha(
    hass: HomeAssistant, runtime_api: MagicMock
) -> None:
    """Keep the existing sensor identity and expose diagnostic offsets."""
    hass.config.time_zone = "Europe/Amsterdam"
    runtime_api.device_info.return_value["time_zone_iana"] = "Europe/Amsterdam"
    await setup(hass)
    state = hass.states.get("sensor.test_box_time_zone_iana")
    assert state is not None
    assert state.state == "Europe/Amsterdam"
    assert state.attributes["home_assistant_time_zone"] == "Europe/Amsterdam"
    assert state.attributes["server_clock_assumption"] == NOTTY_SERVER_TIME_ZONE
    assert state.attributes["device_iana_valid"] is True
    assert state.attributes["device_minus_ha_offset_minutes"] == 0
    runtime_api.litter_action.assert_not_awaited()


def test_timezone_field_still_uses_generic_discovery() -> None:
    """The read-only timezone entity is created only when NOTTY reports it."""
    empty = {"device": {"alias": "box"}, "info": {"today_clean_count": 1}}
    found = {"device": {"time_zone_iana": "Europe/Amsterdam"}, "info": {"today_clean_count": 1}}
    assert "time_zone_iana" not in sensor_keys(empty)
    assert "time_zone_iana" in sensor_keys(found)


def test_catalog_inventory_does_not_include_response_values() -> None:
    """A shareable report must not leak catalog IDs, tokens or private values."""
    response = {
        "data": [
            {"id": 52963, "name": "Europe/Amsterdam", "secret": "private-token"},
            {"id": 92001, "name": "America/New_York"},
        ]
    }
    result = catalog_report(response)
    from json import dumps

    text = dumps(result)
    assert TIME_ZONE_CATALOG_PATH in text
    assert "private-token" not in text
    assert "Europe/Amsterdam" not in text
    assert "52963" not in text
    assert "data[]" in text


async def test_catalog_probe_sends_only_one_read_request() -> None:
    """Never use change_time_zone when discovering server-supported IDs."""
    api = MagicMock()
    api.request = AsyncMock(return_value={"list": []})
    result = await collect_catalog(api)
    assert result == {"list": []}
    api.request.assert_awaited_once_with("GET", TIME_ZONE_CATALOG_PATH)
    api.litter_action.assert_not_called()
