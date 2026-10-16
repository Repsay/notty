import json
from unittest.mock import AsyncMock

import pytest

from custom_components.notty.datapoints import inventory
from custom_components.notty.diagnostics import async_get_config_entry_diagnostics
from scripts import probe_datapoints as probe
from scripts.compare_datapoints import compare


def test_inventory_omits_all_values_and_merges_array_types():
    fields = inventory({"token": "secret-token", "weight": [4, 4.2, None], "online": True})
    assert "secret-token" not in json.dumps(fields)
    assert fields["$.weight[]"] == ["integer", "null", "number"]
    assert fields["$.online"] == ["boolean"]


def test_compare_detects_new_removed_and_changed_types():
    result = compare(
        {"datapoints": {"a": ["integer"], "b": ["string"]}},
        {"datapoints": {"a": ["string"], "c": ["boolean"]}},
    )
    assert list(result["added"]) == ["c"]
    assert list(result["removed"]) == ["b"]
    assert list(result["type_changed"]) == ["a"]


async def test_probe_only_uses_read_methods():
    api = AsyncMock()
    api.devices.return_value = [
        {"user_device_id": "private-box-id", "device_type": "litter_box"},
        {"id": "pet_1", "_notty_source": "pet"},
    ]
    api.pets.return_value = [{"pet_id": "private-pet-id"}]
    api.litter_info.return_value = {"switch_dnd": 1}
    api.litter_related_info.return_value = {}
    api.pet_related_info.return_value = {}
    capture = await probe.collect(api, [])
    api.litter_info.assert_awaited_once_with("private-box-id")
    api.pet_related_info.assert_awaited_once_with("private-pet-id")
    assert {call[0] for call in api.mock_calls} <= {
        "devices",
        "pets",
        "litter_info",
        "litter_related_info",
        "pet_related_info",
    }
    result = probe.report(capture)
    assert "private-box-id" not in json.dumps(result)
    assert "private-pet-id" not in json.dumps(result)


async def test_probe_hides_error_bodies_and_reports_partial_failure():
    api = AsyncMock()
    api.devices.side_effect = probe.load_api.NottyApiError("secret-account")
    api.pets.return_value = []
    capture = await probe.collect(api, [])
    assert capture["errors"] == [{"endpoint": "devices", "error": "request_failed"}]
    assert "secret-account" not in json.dumps(probe.report(capture))


def test_capture_private_permissions_and_no_overwrite(tmp_path):
    path = tmp_path / "test.private.json"
    probe.write_json(path, {"responses": {}})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        probe.write_json(path, {})


async def test_ha_diagnostics_omit_credentials_and_device_ids():
    from types import SimpleNamespace

    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(
            last_update_success=True,
            data={"private-box-id": {"info": {"email": "private@example.test", "token": "secret"}}},
        )
    )
    result = await async_get_config_entry_diagnostics(None, entry)
    serialized = json.dumps(result)
    for secret in ("private-box-id", "private@example.test", "secret"):
        assert secret not in serialized
