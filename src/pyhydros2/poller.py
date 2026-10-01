"""Polling-session lifecycle helper for the device state endpoint.

The state endpoint has a distinct contract from the rest of the API: it
requires an ephemeral poll token from a separate "session" endpoint,
recommends a specific poll interval, and that session must be renewed
before it expires. ``DeviceStatePoller`` owns exactly that lifecycle so
callers (including a future Home Assistant ``DataUpdateCoordinator``) only
need to call ``async_poll()`` on a schedule.

Example integration with a coordinator-style update loop::

    poller = DeviceStatePoller(client)

    async def _async_update_data():
        return await poller.async_poll()

Or drive it standalone::

    async def on_state(state: DeviceState | None):
        if state is not None:
            print(state.mode)

    await poller.run(on_state)

Starting a session (``POST /api/v1/device/state/session``) is rate limited
to 5/hour per device, while a session itself is valid for 6 hours. A
process that restarts often (e.g. during development, or a Home Assistant
reload) can burn through that budget needlessly if it always starts fresh.
Pass ``initial_session`` to seed the poller from a session persisted
elsewhere, and ``on_session_change`` to be notified (and persist) whenever
a new session is started or renewed::

    poller = DeviceStatePoller(
        client,
        initial_session=load_cached_session(),  # may be None, expired, or stale
        on_session_change=save_cached_session,
    )
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional, Union

from .client import HydrosClient
from .const import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_SESSION_RENEW_MARGIN_SECONDS,
    STATE_POLL_MIN_INTERVAL_SECONDS,
)
from .exceptions import HydrosAuthError, HydrosConfigError, HydrosNotFoundError
from .models import DeviceState, SessionResponse

StateCallback = Callable[[Optional[DeviceState]], Union[None, Awaitable[None]]]
SessionCallback = Callable[[SessionResponse], Union[None, Awaitable[None]]]


class DeviceStatePoller:
    """Manages a HYDROS state-polling session for one device.

    Not thread-safe across event loops, but safe for concurrent
    ``async_poll()`` calls on the same loop (session start/renewal is
    serialized internally).
    """

    def __init__(
        self,
        client: HydrosClient,
        *,
        renew_margin_seconds: int = DEFAULT_SESSION_RENEW_MARGIN_SECONDS,
        poll_interval_seconds: Optional[int] = None,
        initial_session: Optional[SessionResponse] = None,
        on_session_change: Optional[SessionCallback] = None,
    ) -> None:
        """
        ``poll_interval_seconds`` overrides the server-recommended cadence
        from the session response. The server's recommendation is often
        more conservative than the documented rate limit; pass e.g.
        ``STATE_POLL_MIN_INTERVAL_SECONDS`` (6s) here to poll at the full
        10 requests/minute the API allows. Values below that floor are
        rejected since they would always eventually 429.

        ``initial_session`` seeds the poller with a previously-persisted
        session, avoiding an unnecessary call to the rate-limited session
        endpoint. If it's expired (or within ``renew_margin_seconds`` of
        expiring), a fresh one is started automatically on first use, same
        as if none had been supplied.

        ``on_session_change`` is invoked (awaited if it returns an
        awaitable) every time a new session is started or renewed, so
        callers can persist it for reuse across restarts.
        """
        if (
            poll_interval_seconds is not None
            and poll_interval_seconds < STATE_POLL_MIN_INTERVAL_SECONDS
        ):
            raise HydrosConfigError(
                f"poll_interval_seconds={poll_interval_seconds} is below the "
                f"documented GET /api/v1/device/state rate limit floor of "
                f"{STATE_POLL_MIN_INTERVAL_SECONDS}s (10 requests/minute)"
            )
        self._client = client
        self._renew_margin = timedelta(seconds=renew_margin_seconds)
        self._poll_interval_override = poll_interval_seconds
        self._on_session_change = on_session_change
        self._session: Optional[SessionResponse] = initial_session
        self._lock = asyncio.Lock()

    @property
    def session(self) -> Optional[SessionResponse]:
        """The current session, if one has been started/seeded, for persistence."""
        return self._session

    @property
    def poll_interval_seconds(self) -> int:
        """Effective polling cadence: override, else server recommendation, else default."""
        if self._poll_interval_override is not None:
            return self._poll_interval_override
        if self._session is not None:
            return self._session.poll_interval_seconds
        return DEFAULT_POLL_INTERVAL_SECONDS

    def _needs_new_session(self) -> bool:
        if self._session is None:
            return True
        return datetime.now(timezone.utc) >= (self._session.expires_at - self._renew_margin)

    async def _ensure_session(self) -> SessionResponse:
        async with self._lock:
            if self._needs_new_session():
                self._session = await self._client.start_state_session()
                if self._on_session_change is not None:
                    result = self._on_session_change(self._session)
                    if inspect.isawaitable(result):
                        await result
        return self._session

    async def async_poll(self) -> Optional[DeviceState]:
        """Poll once, starting or renewing the session as needed.

        Returns ``None`` if no recent state snapshot is available (HTTP 404
        -- the device may be offline or has never reported). Raises for any
        other error, including auth/permission failures.
        """
        session = await self._ensure_session()
        try:
            return await self._client.poll_state(session)
        except HydrosAuthError:
            # Poll token rejected unexpectedly (e.g. revoked out-of-band).
            # Force a fresh session once before giving up.
            async with self._lock:
                self._session = None
            session = await self._ensure_session()
            try:
                return await self._client.poll_state(session)
            except HydrosNotFoundError:
                return None
        except HydrosNotFoundError:
            return None

    async def run(
        self,
        callback: StateCallback,
        *,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Poll continuously at the session's recommended interval.

        Runs until ``stop_event`` is set (a new ``asyncio.Event`` is created
        if none is supplied, which means "run forever" unless the caller
        keeps a reference to cancel the task instead).
        """
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            state = await self.async_poll()
            result = callback(state)
            if inspect.isawaitable(result):
                await result
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass
