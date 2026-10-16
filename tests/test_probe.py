import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.notty.datapoints import inventory
from custom_components.notty.diagnostics import async_get_config_entry_diagnostics
from scripts import probe_datapoints as probe
from scripts.compare_datapoints import compare


def probe_args(**kwargs):
    return SimpleNamespace(
        **{
            "from_file": None,
            "output": None,
            "capture_raw": None,
            "session_file": None,
            "device_id": [],
            **kwargs,
        }
    )


async def test_session_saved_without_one_time_code_or_password(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTTY_EMAIL", "test@example.test")
    monkeypatch.setenv("NOTTY_VERIFICATION_CODE", "one-time-secret")
    monkeypatch.setenv("NOTTY_PASSWORD", "private-password")
    api = MagicMock(token=None, user_id="test-user", email="test@example.test", region_code="NL")

    async def login():
        api.token = "test-token"

    api.login = AsyncMock(side_effect=login)
    session_file = tmp_path / "session.private.json"
    args = probe_args(session_file=session_file, output=tmp_path / "report.json")
    with (
        patch.object(probe.load_api, "NottyApi", return_value=api),
        patch.object(probe, "collect", AsyncMock(return_value={"responses": {}, "errors": []})),
    ):
        assert await probe.run(args) == 0
    saved = json.loads(session_file.read_text())
    assert saved == {
        "access_token": "test-token",
        "user_id": "test-user",
        "email": "test@example.test",
        "region_code": "NL",
    }
    assert session_file.stat().st_mode & 0o777 == 0o600
    api.login.assert_awaited_once()


async def test_saved_session_reused_without_login(tmp_path, monkeypatch):
    for key in ("NOTTY_EMAIL", "NOTTY_ACCESS_TOKEN", "NOTTY_USER_ID"):
        monkeypatch.delenv(key, raising=False)
    session_file = tmp_path / "session.private.json"
    probe.write_json(
        session_file,
        {
            "email": "test@example.test",
            "access_token": "saved-token",
            "user_id": "test-user",
            "region_code": "NL",
        },
    )
    api = MagicMock(token="saved-token")
    api.login = AsyncMock()
    with (
        patch.object(probe.load_api, "NottyApi", return_value=api) as cls,
        patch.object(probe, "collect", AsyncMock(return_value={"responses": {}, "errors": []})),
    ):
        assert await probe.run(probe_args(session_file=session_file)) == 0
    assert cls.call_args.kwargs["token"] == "saved-token"
    assert cls.call_args.kwargs["user_id"] == "test-user"
    api.login.assert_not_awaited()


async def test_reject_existing_output_before_consuming_login_code(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("existing")
    with patch.object(probe.load_api, "NottyApi") as cls:
        with pytest.raises(FileExistsError):
            await probe.run(probe_args(output=output))
    cls.assert_not_called()


async def test_session_must_use_ignored_private_suffix(tmp_path):
    with pytest.raises(ValueError, match="private"):
        await probe.run(probe_args(session_file=tmp_path / "session.json"))


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


async def test_probe_recognizes_live_device_name_shape():
    """Physical devices omit device_type/product_name/model in real responses."""
    api = AsyncMock()
    api.devices.return_value = [
        {
            "user_device_id": "synthetic-box-id",
            "device_name": "Cat Automatic Litter Box",
            "lb_mode": 1,
            "status_id": 1,
            "time_zone_iana": "Europe/Amsterdam",
            "_notty_source": "device",
        }
    ]
    api.pets.return_value = []
    api.litter_info.return_value = {"status_id": 1}
    api.litter_related_info.return_value = {}
    capture = await probe.collect(api, [])
    api.litter_info.assert_awaited_once_with("synthetic-box-id")
    api.litter_related_info.assert_awaited_once_with("synthetic-box-id")
    assert capture["responses"]["litter_boxes[0].info"] == {"status_id": 1}


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
