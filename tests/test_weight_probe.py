"""Read-only weight probing, private output and conservative evidence checks."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.notty.api import JsonObject, JsonValue
from scripts import probe_datapoints, probe_weights, weight_report

PRIVATE_MODE = 0o600
EXPECTED_ENUM = "unverified_enum"
EXPECTED_SETTING = "profile_setting"
GET = "GET"
FIELD_VALUE = "reported_value"
SERIES_COUNT = 2
EXPECTED_DETAIL_PATH = "/device/litter_box/pet_data_detail/123?pet_id=7"
FORBIDDEN_PATH_PARTS = ("pet_id=8", "pet_id=99", "/456")
PRIVATE_MARKER = "secret-token"


def capture() -> JsonObject:
    """Return invented profile and measured-series candidates.

    Returns:
        A synthetic private weight capture.
    """
    return {
        "schema_version": 1,
        "errors": [],
        "sources": [
            {
                "label": "pet[1].profile",
                "kind": "profile",
                "identity": "pet:7:profile",
                "data": {"name": "Secret cat", "pet_id": 7, "weight": 4.8, "weight_unit": 1},
            },
            {
                "label": "box[1].pet[1].detail",
                "kind": "detail",
                "identity": "box:123:pet:7:detail",
                "data": {
                    "private-person-key": [{"weight": 4.1, "weight_unit": "kg", "date": "2026-10-17", "time": "08:00"}]
                },
            },
        ],
    }


def test_report_separates_profile_and_candidate_without_leaking_values() -> None:
    """Default reports keep personal keys, names, measurements and IDs private."""
    result = weight_report.report(capture())
    text = json.dumps(result)
    for secret in ("Secret cat", "private-person-key", "4.8", "4.1", "2026-10-17", "08:00", "pet:7", "box:123"):
        assert secret not in text
    sources = result["sources"]
    assert sources[0]["fields"][0]["role"] == EXPECTED_SETTING
    assert sources[0]["fields"][0]["unit"]["status"] == EXPECTED_ENUM
    assert sources[1]["fields"][0]["timestamp_context"] == {"date": "str", "time": "str"}
    assert FIELD_VALUE not in sources[1]["fields"][0]


@pytest.mark.parametrize("value", [True, False, 0, -1, "nan", "inf", "4 kg", None, float("inf")])
def test_invalid_weight_is_not_a_measurement(value: JsonValue) -> None:
    """Nonfinite, missing and Boolean weights never count as valid samples."""
    assert weight_report.positive_number(value) is None


def test_series_and_changed_timestamp_are_detected_without_claiming_a_new_visit() -> None:
    """A same-weight new timestamp is visible independently of numeric changes."""
    before = capture()
    after = deepcopy(before)
    after["sources"][1]["data"]["private-person-key"][0]["time"] = "09:00"
    comparison = weight_report.compare_captures(before, after)
    assert comparison["sources"][1]["weight_response_changed"] is False
    assert comparison["sources"][1]["timestamp_or_unit_context_changed"] is True
    after["sources"][1]["data"] = {"weight": [4.0, 4.1], "duration": [90, 100]}
    fields = weight_report.report(after)["sources"][1]["fields"]
    assert len(fields) == SERIES_COUNT


async def test_collector_calls_get_only_and_scopes_history_to_bound_account_pets() -> None:
    """No write, login, unbound-pet or foreign-account history endpoint is invoked."""
    api = MagicMock()
    api.user_devices = AsyncMock(
        return_value=[
            {"user_device_id": 123, "device_type": "litter_box"},
            {"user_device_id": 456, "device_type": "feeder"},
        ]
    )
    replies: dict[str, JsonValue] = {
        "/pet/list": [{"pet_id": 7}, {"pet_id": 8}],
        "/device/get_associated_pets/123": [
            {"pet_id": 7, "is_associated": True},
            {"pet_id": 8, "is_associated": False},
            {"pet_id": 99, "is_associated": True},
        ],
    }
    api.request = AsyncMock(side_effect=lambda _method, path: replies.get(path, {}))
    result = await probe_weights.WeightCollector(api).collect([], [])
    assert result["errors"] == []
    paths = [call.args[1] for call in api.request.await_args_list]
    assert all(call.args[0] == GET for call in api.request.await_args_list)
    assert EXPECTED_DETAIL_PATH in paths
    assert not any(part in path for path in paths for part in FORBIDDEN_PATH_PARTS)


async def test_foreign_target_prevents_data_reads() -> None:
    """A CLI target cannot bypass account discovery."""
    api = MagicMock(request=AsyncMock(return_value=[{"pet_id": 7}]))
    with pytest.raises(ValueError, match="current account"):
        await probe_weights.WeightCollector(api).collect([], ["99"])
    api.request.assert_awaited_once_with(GET, "/pet/list")


async def test_optional_failure_is_recorded_without_echoing_error_body() -> None:
    """A failed history route is not silently reported as an empty history."""
    api = MagicMock(request=AsyncMock(side_effect=probe_datapoints.load_api.NottyApiError("secret-token")))
    collector = probe_weights.WeightCollector(api)
    await collector.read("pet[1].profile", "profile", "pet:7:profile", "/pet/info/7")
    assert len(collector.errors) == 1
    assert PRIVATE_MARKER not in json.dumps(collector.errors)


async def test_offline_analysis_never_opens_a_network_session_and_outputs_owner_only(tmp_path: Path) -> None:
    """Private captures can be reanalysed without tokens or Home Assistant."""
    source = tmp_path / "weight.private.json"
    output = tmp_path / "report.json"
    probe_datapoints.write_json(source, capture())
    with patch.object(probe_weights.aiohttp, "ClientSession", side_effect=AssertionError("network")):
        await probe_weights.run(probe_weights.WeightProbeOptions(from_file=source, output=output))
    assert output.stat().st_mode & 0o777 == PRIVATE_MODE


@pytest.mark.parametrize(
    "options",
    [
        probe_weights.WeightProbeOptions(session_file=Path("session.private.json"), capture_raw=Path("unsafe.json")),
        probe_weights.WeightProbeOptions(
            session_file=Path("session.private.json"), output=Path("unsafe.json"), show_values=True
        ),
        probe_weights.WeightProbeOptions(from_file=Path("capture.private.json"), device_id=["123"]),
    ],
)
async def test_bad_paths_and_modes_fail_before_network(options: probe_weights.WeightProbeOptions) -> None:
    """Sensitive captures and value-bearing reports cannot use a public filename."""
    with (
        patch.object(probe_weights.aiohttp, "ClientSession", side_effect=AssertionError("network")),
        pytest.raises(ValueError, match=r"private|Offline"),
    ):
        await probe_weights.run(options)


def test_daily_weight_in_profile_response_is_still_a_measurement_candidate() -> None:
    """Endpoint origin does not make today/yesterday values editable profile settings."""
    value = capture()
    value["sources"][0]["data"]["today_weight"] = 4.1
    fields = weight_report.report(value)["sources"][0]["fields"]
    assert fields[-1]["role"] != EXPECTED_SETTING
