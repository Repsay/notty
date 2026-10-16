from unittest.mock import patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def api_mock():
    with patch("custom_components.notty.config_flow.NottyApi", autospec=True) as cls:
        api = cls.return_value
        api.token = "test-token"
        api.refresh_token = "test-refresh"
        api.user_id = "test-user"
        yield api


@pytest.fixture
def runtime_api():
    with patch("custom_components.notty.NottyApi", autospec=True) as cls:
        api = cls.return_value
        api.token = "test-token"
        api.refresh_token = None
        api.user_id = "test-user"
        api.devices.return_value = [
            {"user_device_id": "box-1", "device_type": "litter_box", "alias": "Test box"}
        ]
        api.device_info.return_value = {
            "status_id": 1,
            "mode": 1,
            "switch_key": 0,
            "switch_dnd": 1,
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
