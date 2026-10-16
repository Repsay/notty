from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


# This must precede the HA plugin's timer-tracking fixtures during setup.
@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integration discovery before fixture timer tracking."""
    del enable_custom_integrations


@pytest.fixture
def api_mock() -> Iterator[MagicMock]:
    """Api mock.

    Yields:
        The mocked NOTTY API client.
    """
    with patch("custom_components.notty.config_flow.NottyApi", autospec=True) as cls:
        api = cls.return_value
        api.token = SAMPLE_SESSION
        api.refresh_token = SAMPLE_RENEWAL
        api.user_id = "test-user"
        yield api


@pytest.fixture
def runtime_api() -> Iterator[MagicMock]:
    """Runtime api.

    Yields:
        The mocked NOTTY API client.
    """
    with patch("custom_components.notty.bootstrap.NottyApi", autospec=True) as cls:
        api = cls.return_value
        api.token = SAMPLE_SESSION
        api.refresh_token = None
        api.user_id = "test-user"
        api.devices.return_value = [{"user_device_id": "box-1", "device_type": "litter_box", "alias": "Test box"}]
        api.device_info.return_value = {
            "status_id": 1,
            "mode": 1,
            "switch_key": 0,
            "switch_dnd": 1,
            "led": 2,
            "dnd_begin_time": "22:00",
            "dnd_end_time": "07:00",
            "today_clean_count": 2,
            "events": [],
        }
        api.litter_related_info.return_value = {
            "associated_pets": [{"pet_id": "cat-1", "name": "Test cat", "weight": 4.2}]
        }
        api.unread_message_count.return_value = 0
        yield api


SAMPLE_SESSION = "test-token"

SAMPLE_RENEWAL = "test-refresh"
