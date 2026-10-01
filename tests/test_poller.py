"""Tests for pyhydros2.poller.DeviceStatePoller using a mocked HydrosClient."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from pyhydros2 import HydrosAuthError, HydrosConfigError, HydrosNotFoundError
from pyhydros2.const import STATE_POLL_MIN_INTERVAL_SECONDS
from pyhydros2.models import DeviceState, SessionResponse
from pyhydros2.poller import DeviceStatePoller


def _session(expires_in_seconds: int = 21600, poll_interval: int = 30) -> SessionResponse:
    return SessionResponse(
        poll_url="https://api.coralvuehydros.com/api/v1/device/state?id=abc",
        poll_token="tok",
        duration_seconds=21600,
        poll_interval_seconds=poll_interval,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
    )


async def test_async_poll_starts_session_once():
    client = AsyncMock()
    client.start_state_session.return_value = _session()
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})

    poller = DeviceStatePoller(client)
    state = await poller.async_poll()
    assert state is not None
    assert state.mode == "Normal"
    assert client.start_state_session.await_count == 1

    # Second poll reuses the existing session (no renewal needed yet).
    await poller.async_poll()
    assert client.start_state_session.await_count == 1
    assert client.poll_state.await_count == 2


async def test_async_poll_renews_expiring_session():
    client = AsyncMock()
    # First session is already within the renewal margin.
    client.start_state_session.side_effect = [_session(expires_in_seconds=60), _session()]
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})

    poller = DeviceStatePoller(client, renew_margin_seconds=1800)
    await poller.async_poll()
    await poller.async_poll()
    assert client.start_state_session.await_count == 2


async def test_async_poll_returns_none_on_404():
    client = AsyncMock()
    client.start_state_session.return_value = _session()
    client.poll_state.side_effect = HydrosNotFoundError("no state", status_code=404)

    poller = DeviceStatePoller(client)
    assert await poller.async_poll() is None


async def test_async_poll_retries_once_on_auth_error():
    client = AsyncMock()
    client.start_state_session.side_effect = [_session(), _session()]
    client.poll_state.side_effect = [
        HydrosAuthError("invalid token", status_code=401),
        DeviceState.from_dict({"mode": "Feeding"}),
    ]

    poller = DeviceStatePoller(client)
    state = await poller.async_poll()
    assert state is not None
    assert state.mode == "Feeding"
    assert client.start_state_session.await_count == 2


async def test_run_invokes_callback_until_stopped():
    client = AsyncMock()
    client.start_state_session.return_value = _session(poll_interval=0)
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})

    poller = DeviceStatePoller(client)
    stop_event = asyncio.Event()
    calls = []

    async def callback(state):
        calls.append(state)
        if len(calls) >= 3:
            stop_event.set()

    await asyncio.wait_for(poller.run(callback, stop_event=stop_event), timeout=5)
    assert len(calls) == 3


def test_poll_interval_override_takes_precedence_over_session():
    client = AsyncMock()
    poller = DeviceStatePoller(client, poll_interval_seconds=STATE_POLL_MIN_INTERVAL_SECONDS)
    assert poller.poll_interval_seconds == STATE_POLL_MIN_INTERVAL_SECONDS


async def test_poll_interval_override_used_even_after_session_starts():
    client = AsyncMock()
    client.start_state_session.return_value = _session(poll_interval=30)
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})

    poller = DeviceStatePoller(client, poll_interval_seconds=STATE_POLL_MIN_INTERVAL_SECONDS)
    await poller.async_poll()
    assert poller.poll_interval_seconds == STATE_POLL_MIN_INTERVAL_SECONDS


def test_poll_interval_below_rate_limit_floor_rejected():
    client = AsyncMock()
    with pytest.raises(HydrosConfigError):
        DeviceStatePoller(client, poll_interval_seconds=STATE_POLL_MIN_INTERVAL_SECONDS - 1)


async def test_initial_session_reused_without_starting_a_new_one():
    client = AsyncMock()
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})
    seeded = _session()

    poller = DeviceStatePoller(client, initial_session=seeded)
    assert poller.session is seeded
    state = await poller.async_poll()
    assert state is not None
    assert client.start_state_session.await_count == 0
    assert poller.session is seeded


async def test_initial_session_expired_triggers_fresh_start():
    client = AsyncMock()
    client.start_state_session.return_value = _session()
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})
    expired = _session(expires_in_seconds=60)

    poller = DeviceStatePoller(client, initial_session=expired, renew_margin_seconds=1800)
    await poller.async_poll()
    assert client.start_state_session.await_count == 1
    assert poller.session is not expired


async def test_on_session_change_invoked_on_start_and_renewal():
    client = AsyncMock()
    client.start_state_session.side_effect = [_session(expires_in_seconds=60), _session()]
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})
    seen = []

    poller = DeviceStatePoller(
        client, renew_margin_seconds=1800, on_session_change=seen.append
    )
    await poller.async_poll()
    await poller.async_poll()
    assert len(seen) == 2
    assert seen[-1] is poller.session


async def test_on_session_change_supports_async_callback():
    client = AsyncMock()
    client.start_state_session.return_value = _session()
    client.poll_state.return_value = DeviceState.from_dict({"mode": "Normal"})
    seen = []

    async def on_change(session):
        seen.append(session)

    poller = DeviceStatePoller(client, on_session_change=on_change)
    await poller.async_poll()
    assert len(seen) == 1
