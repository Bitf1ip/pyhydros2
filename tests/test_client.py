"""Tests for pyhydros2.client.HydrosClient using aioresponses."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import aiohttp
import pytest
from aioresponses import aioresponses

from pyhydros2 import (
    HydrosAPIError,
    HydrosAuthError,
    HydrosBadRequestError,
    HydrosClient,
    HydrosConfigError,
    HydrosConnectionError,
    HydrosForbiddenError,
    HydrosNotFoundError,
    HydrosRateLimitError,
    HydrosServerError,
)
from pyhydros2.models import SessionResponse

BASE_URL = "https://api.coralvuehydros.com"


@pytest.fixture
def mocked():
    with aioresponses() as m:
        yield m


async def test_get_device(client, mocked):
    mocked.get(
        f"{BASE_URL}/api/v1/device",
        payload=[
            {
                "deviceId": "a0b765227294",
                "friendlyName": "Display Tank Controller",
                "type": "X4",
                "owner": "user@example.com",
                "shared": False,
            }
        ],
    )
    device = await client.get_device()
    assert device.device_id == "a0b765227294"
    assert device.type == "X4"


async def test_start_state_session_and_poll(client, mocked):
    mocked.post(
        f"{BASE_URL}/api/v1/device/state/session",
        payload={
            "pollUrl": f"{BASE_URL}/api/v1/device/state?id=3f1a2b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c",
            "pollToken": "poll-token-123",
            "durationSeconds": 21600,
            "pollIntervalSeconds": 30,
            "expiresAt": "2026-06-27T02:47:01Z",
        },
    )
    session = await client.start_state_session()
    assert session.poll_token == "poll-token-123"

    mocked.get(
        f"{BASE_URL}/api/v1/device/state?id=3f1a2b4c-5d6e-7f8a-9b0c-1d2e3f4a5b6c",
        payload={"mode": "Normal", "temperatureI": 275},
    )
    state = await client.poll_state(session)
    assert state.mode == "Normal"
    assert state.temperature_celsius == 34.375


async def test_poll_state_404_raises_not_found(client, mocked):
    session = SessionResponse(
        poll_url=f"{BASE_URL}/api/v1/device/state?id=abc",
        poll_token="tok",
        duration_seconds=21600,
        poll_interval_seconds=30,
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    mocked.get(
        f"{BASE_URL}/api/v1/device/state?id=abc",
        status=404,
        payload={"error": "No recent state"},
    )
    with pytest.raises(HydrosNotFoundError):
        await client.poll_state(session)


async def test_get_overrides(client, mocked):
    mocked.get(
        f"{BASE_URL}/api/v1/device/overrides",
        payload={
            "status": "delivered",
            "updatedAt": 1693879108136,
            "overrides": {
                "7f3a2b1c-4d5e-4f6a-8b9c-0d1e2f3a4b5c": {
                    "name": "Return Left",
                    "desired": 7500,
                    "reported": 7500,
                }
            },
        },
    )
    state = await client.get_overrides()
    assert state.delivered
    assert state.overrides["7f3a2b1c-4d5e-4f6a-8b9c-0d1e2f3a4b5c"].desired == 7500


async def test_put_overrides(client, mocked):
    mocked.put(
        f"{BASE_URL}/api/v1/device/overrides",
        status=202,
        payload={
            "status": "pending",
            "updatedAt": 1693879108136,
            "overrides": {
                "7f3a2b1c-4d5e-4f6a-8b9c-0d1e2f3a4b5c": {
                    "name": "Return Left",
                    "desired": 7500,
                    "reported": None,
                }
            },
        },
    )
    state = await client.put_overrides({"7f3a2b1c-4d5e-4f6a-8b9c-0d1e2f3a4b5c": 7500})
    assert state.pending


async def test_delete_override_url_encodes_key(client, mocked):
    mocked.delete(
        f"{BASE_URL}/api/v1/device/overrides/weird%2Fkey",
        status=202,
        payload={"status": "pending", "updatedAt": 1, "overrides": {}},
    )
    state = await client.delete_override("weird/key")
    assert state.pending


async def test_send_override_command(client, mocked):
    mocked.post(
        f"{BASE_URL}/api/v1/device/overrides/mode/command",
        status=202,
        payload={"command": "Feeding", "published": True, "deviceConnected": True},
    )
    result = await client.set_mode("Feeding")
    assert result.command == "Feeding"
    assert result.published is True


async def test_get_override_metadata(client, mocked):
    mocked.get(
        f"{BASE_URL}/api/v1/device/overrides/metadata",
        payload=[
            {"key": "abc", "name": "Return Left", "type": "level", "min": 0, "max": 10000},
            {"key": "mode", "name": "Mode", "type": "mode", "commands": {"Feeding": {}}},
        ],
    )
    entries = await client.get_override_metadata()
    assert len(entries) == 2
    assert entries[1].is_mode


async def test_query_logs(client, mocked):
    mocked.get(
        re.compile(rf"^{re.escape(BASE_URL)}/api/v1/device/logs(\?.*)?$"),
        payload={
            "thingName": "a0b765227294",
            "start": 0,
            "end": 1000,
            "resolution": "10m",
            "resolutionMs": 600000,
            "retentionDays": 33,
            "points": 1,
            "series": {
                "Temperature 1": {
                    "type": "Tmp",
                    "sensorType": "analog",
                    "points": [[500, 25.5, ""]],
                }
            },
        },
    )
    result = await client.query_logs(0, 1000)
    assert result.points == 1
    assert result.series["Temperature 1"].points == [(500, 25.5, "")]


async def test_export_logs_and_download(client, mocked):
    mocked.get(
        re.compile(rf"^{re.escape(BASE_URL)}/api/v1/device/logs/export(\?.*)?$"),
        payload={
            "url": "https://exports.coralvuehydros.com/signed/abc",
            "expiresAt": 1700000000000,
            "format": "csv",
            "points": 100,
            "resolution": "10m",
            "timezone": "UTC",
        },
    )
    export = await client.export_logs(0, 1000)
    assert export.format == "csv"

    mocked.get("https://exports.coralvuehydros.com/signed/abc", body=b"timestamp,value\n")
    content = await client.download_export(export)
    assert content == b"timestamp,value\n"


async def test_get_dosing_totals_today_sums_and_defaults_missing(client, mocked):
    now = datetime(2026, 9, 30, 15, 30, 0).astimezone()
    mocked.get(
        re.compile(rf"^{re.escape(BASE_URL)}/api/v1/device/logs(\?.*)?$"),
        payload={
            "thingName": "a0b765227294",
            "start": 0,
            "end": 1000,
            "resolution": "events",
            "resolutionMs": None,
            "retentionDays": 33,
            "points": 2,
            "series": {
                "Dosing Pump 1": {
                    "type": "Dos",
                    "sensorType": "event",
                    "points": [
                        [1000, 1, "Dose NO3 Dosed 1.0 ml"],
                        [2000, 1, "Manual Dosed 0.5 ml"],
                    ],
                }
            },
        },
    )
    totals = await client.get_dosing_totals_today(["Dosing Pump 1", "Dosing Pump 2"], now=now)
    assert totals == {"Dosing Pump 1": 1.5, "Dosing Pump 2": 0.0}


async def test_get_dosing_totals_today_empty_names_skips_request(client):
    assert await client.get_dosing_totals_today([]) == {}


@pytest.mark.parametrize(
    "status,exc_cls",
    [
        (400, HydrosBadRequestError),
        (401, HydrosAuthError),
        (403, HydrosForbiddenError),
        (404, HydrosNotFoundError),
        (429, HydrosRateLimitError),
        (500, HydrosServerError),
    ],
)
async def test_error_status_mapping(client, mocked, status, exc_cls):
    mocked.get(
        f"{BASE_URL}/api/v1/device",
        status=status,
        payload={"error": "boom"},
    )
    with pytest.raises(exc_cls) as excinfo:
        await client.get_device()
    assert excinfo.value.status_code == status
    assert str(excinfo.value) == "boom"


@pytest.mark.parametrize(
    "error", [aiohttp.ClientConnectionError("down"), asyncio.TimeoutError()]
)
async def test_transport_errors_raise_connection_error(client, mocked, error):
    mocked.get(f"{BASE_URL}/api/v1/device", exception=error)
    with pytest.raises(HydrosConnectionError) as excinfo:
        await client.get_device()
    assert excinfo.value.status_code is None
    assert isinstance(excinfo.value, HydrosAPIError)


@pytest.mark.parametrize("payload", [[], {"unexpected": True}, [{"deviceId": "x"}]])
async def test_malformed_response_raises_api_error(client, mocked, payload):
    mocked.get(f"{BASE_URL}/api/v1/device", payload=payload)
    with pytest.raises(HydrosAPIError, match="Unexpected response"):
        await client.get_device()


async def test_non_json_success_body_raises_api_error(client, mocked):
    mocked.get(f"{BASE_URL}/api/v1/device/overrides/metadata", body="<html>oops</html>")
    with pytest.raises(HydrosAPIError, match="Unexpected response"):
        await client.get_override_metadata()


def test_rejects_non_https_base_url():
    with pytest.raises(HydrosConfigError, match="HTTPS"):
        HydrosClient("provider", "device", base_url="http://api.coralvuehydros.com")


async def test_injected_session_is_not_closed():
    async with aiohttp.ClientSession() as session:
        client = HydrosClient("provider", "device", session=session)
        await client.close()
        assert not session.closed
