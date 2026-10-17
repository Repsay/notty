"""Cloud daily weight summaries preserve units and never invent a weigh-in timestamp."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
import pytest

from tests.test_feature_ui import configure
from tests.test_lifecycle import setup

ENTITY = "sensor.milo_today_weight"
UNKNOWN = "unknown"
MEASUREMENT = "measurement"
FIELD_TODAY = "today_weight"
UNIT_KG = "kg"
FRESHNESS = "not_reported"


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        (1, 4.2, 4.2),
        ("1", "4.2", 4.2),
        (2, 10, 4.5359237),
        ("2", "10", 4.5359237),
        (None, 4.2, None),
        (99, 4.2, None),
        (True, 4.2, None),
        (1.0, 4.2, None),
        (1, False, None),
        (1, 0, None),
        (1, -1, None),
        (1, "nan", None),
        (1, "inf", None),
        (1, 10**400, None),
        (1, None, None),
    ],
)
async def test_weight_units_and_unknown_values(
    hass: HomeAssistant, runtime_api: MagicMock, unit: object, value: object, expected: float | None
) -> None:
    """Keep one statistics unit while rejecting invalid values or unknown unit codes."""
    profile, _ = configure(runtime_api)
    profile.update({"today_weight": value, "weight_unit": unit})
    await setup(hass)
    state = hass.states.get(ENTITY)
    assert state is not None
    if expected is None:
        assert state.state == UNKNOWN
    else:
        assert float(state.state) == pytest.approx(expected)
    assert state.attributes["unit_of_measurement"] == UNIT_KG
    assert state.attributes["state_class"] == MEASUREMENT
    assert state.attributes["measurement_time"] is None
    assert state.attributes["source_field"] == FIELD_TODAY
    assert state.attributes["measurement_freshness"] == FRESHNESS
    runtime_api.save_pet_weight.assert_not_awaited()


async def test_late_weight_discovery_missing_data_and_unit_change(hass: HomeAssistant, runtime_api: MagicMock) -> None:
    """Discover optional weights once and do not reuse yesterday/profile values on data loss."""
    profile, _ = configure(runtime_api)
    entry = await setup(hass)
    assert hass.states.get(ENTITY) is None
    profile.update({"today_weight": 10, "yesterday_weight": 11, "weight_unit": 2})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(ENTITY).state) == pytest.approx(4.5359237)
    profile.pop("today_weight")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == UNKNOWN
    profile.update({"today_weight": 4.2, "weight_unit": 1})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(ENTITY).state) == pytest.approx(4.2)
    assert len([state for state in hass.states.async_all() if state.entity_id == ENTITY]) == 1
