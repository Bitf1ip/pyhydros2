"""Async client for the HYDROS Public API.

Design notes
------------
- Async-only (``aiohttp``), by design: Home Assistant's event loop cannot
  block on synchronous HTTP calls, and the old MQTT-based ``pyhydros``
  required wrapping every call in an executor job. This client is meant to
  be awaited directly from a coordinator.
- One ``HydrosClient`` is scoped to a single device key, matching the API's
  own model (a device key resolves to exactly one device; there is no
  multi-device listing endpoint). A Home Assistant config entry that manages
  several collectives should hold one client per device key.
- The device *state* document is intentionally opaque (see ``models.DeviceState``).
- This client does not retry automatically. ``HydrosRateLimitError`` (429)
  and ``HydrosConnectionError`` (no response/timeout) are transient;
  ``HydrosAuthError``/``HydrosForbiddenError``
  are not. Callers (or ``poller.DeviceStatePoller`` for the state endpoint)
  decide retry/backoff policy.
"""

from __future__ import annotations

import asyncio
import json as _json
from contextlib import contextmanager
from datetime import datetime
from types import TracebackType
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Type, TypeVar
from urllib.parse import quote

import aiohttp

from . import auth
from .const import DEFAULT_BASE_URL
from .exceptions import (
    HydrosAPIError,
    HydrosAuthError,
    HydrosBadRequestError,
    HydrosConfigError,
    HydrosConnectionError,
    HydrosForbiddenError,
    HydrosNotFoundError,
    HydrosPayloadTooLargeError,
    HydrosRateLimitError,
    HydrosServerError,
)
from .models import (
    CommandResult,
    Device,
    DeviceState,
    LogExportResult,
    LogQueryResult,
    LogSeriesDiscovery,
    OverrideMetadataEntry,
    OverrideState,
    SessionResponse,
)

_STATUS_EXCEPTIONS = {
    400: HydrosBadRequestError,
    401: HydrosAuthError,
    403: HydrosForbiddenError,
    404: HydrosNotFoundError,
    413: HydrosPayloadTooLargeError,
    429: HydrosRateLimitError,
    500: HydrosServerError,
    502: HydrosServerError,
    503: HydrosServerError,
}


_T = TypeVar("_T")


def _raise_for_status(status: int, payload: Any) -> None:
    message = "HYDROS API error"
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        message = payload["error"]
    exc_cls = _STATUS_EXCEPTIONS.get(status, HydrosAPIError)
    raise exc_cls(message, status_code=status, payload=payload)


def _parse(parser: Callable[[Any], _T], data: Any) -> _T:
    """Run a response parser, reporting a malformed body as ``HydrosAPIError``
    instead of a bare ``KeyError``/``TypeError`` from deep inside a model.
    """
    try:
        return parser(data)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as err:
        raise HydrosAPIError(
            f"Unexpected response from the HYDROS API ({err!r})", payload=data
        ) from err


@contextmanager
def _wrap_transport_errors(timeout: Optional[float]) -> Iterator[None]:
    try:
        yield
    except asyncio.TimeoutError as err:
        raise HydrosConnectionError(
            f"Timed out after {timeout:g}s waiting for the HYDROS API"
        ) from err
    except aiohttp.ClientError as err:
        raise HydrosConnectionError(f"Could not reach the HYDROS API: {err}") from err


class HydrosClient:
    """Async client scoped to a single HYDROS device key.

    Usage::

        async with HydrosClient(provider_key, device_key) as client:
            device = await client.get_device()
    """

    def __init__(
        self,
        provider_key: str,
        device_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[aiohttp.ClientSession] = None,
        request_timeout: float = 10.0,
    ) -> None:
        if not base_url.lower().startswith("https://"):
            raise HydrosConfigError(
                "base_url must use HTTPS: the API keys are sent with every request"
            )
        self._auth_header = auth.build_provider_v1_header(provider_key, device_key)
        self._base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> "HydrosClient":
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise HydrosAPIError(
                "HydrosClient has no active session; use 'async with HydrosClient(...)' "
                "or pass an existing aiohttp.ClientSession."
            )
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        bearer: Optional[str] = None,
    ) -> tuple[int, Any]:
        session = self._ensure_session()
        url = f"{self._base_url}{path}"
        headers = {"Authorization": bearer if bearer is not None else self._auth_header}
        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )
        with _wrap_transport_errors(self._timeout.total):
            async with session.request(
                method,
                url,
                params=clean_params,
                json=json_body,
                headers=headers,
                timeout=self._timeout,
            ) as resp:
                status = resp.status
                raw = await resp.read()
        data: Any = None
        if raw:
            try:
                data = _json.loads(raw)
            except ValueError:
                data = None
        if status >= 400:
            _raise_for_status(status, data)
        return status, data

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    async def get_device(self) -> Device:
        """``GET /api/v1/device`` -- return the device bound to this key."""
        _, data = await self._request("GET", "/api/v1/device")
        return _parse(lambda body: Device.from_dict(body[0]), data)

    # ------------------------------------------------------------------
    # Sessions / State
    # ------------------------------------------------------------------

    async def start_state_session(self) -> SessionResponse:
        """``POST /api/v1/device/state/session`` -- start a polling session.

        Rate limited to 5 starts/hour per device; renew well before
        ``expires_at`` rather than starting a fresh session each poll.
        """
        _, data = await self._request("POST", "/api/v1/device/state/session")
        return _parse(SessionResponse.from_dict, data)

    async def poll_state(self, session: SessionResponse) -> DeviceState:
        """``GET`` the session's ``pollUrl`` using its ``pollToken``.

        Raises ``HydrosNotFoundError`` if no recent state snapshot is
        available (device may be offline or never connected).
        """
        session_id = _extract_session_id(session.poll_url)
        _, data = await self._request(
            "GET",
            "/api/v1/device/state",
            params={"id": session_id},
            bearer=session.poll_token,
        )
        return _parse(DeviceState.from_dict, data)

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    async def get_overrides(self) -> OverrideState:
        """``GET /api/v1/device/overrides`` -- current override document."""
        _, data = await self._request("GET", "/api/v1/device/overrides")
        return _parse(OverrideState.from_dict, data)

    async def put_overrides(
        self,
        values: Mapping[str, Any],
        *,
        receipt: bool = False,
    ) -> OverrideState:
        """``PUT /api/v1/device/overrides`` -- set or clear output overrides.

        ``values`` maps stable output keys (from ``get_override_metadata``)
        to the desired value, or ``None`` to clear that key inline. Merge
        semantics: only the keys provided are affected.
        """
        params = {"receipt": "1"} if receipt else None
        _, data = await self._request(
            "PUT", "/api/v1/device/overrides", params=params, json_body=dict(values)
        )
        return _parse(OverrideState.from_dict, data)

    async def delete_override(self, key: str, *, receipt: bool = False) -> OverrideState:
        """``DELETE /api/v1/device/overrides/{key}`` -- clear one override."""
        params = {"receipt": "1"} if receipt else None
        _, data = await self._request(
            "DELETE", f"/api/v1/device/overrides/{quote(key, safe='')}", params=params
        )
        return _parse(OverrideState.from_dict, data)

    async def send_override_command(
        self,
        key: str,
        command: str,
        *,
        value: Optional[int] = None,
        receipt: bool = False,
    ) -> CommandResult:
        """``POST /api/v1/device/overrides/{key}/command`` -- momentary command.

        Use ``key="mode"`` with ``command=<mode name>`` to flip the device's
        operating mode (see ``set_mode``).
        """
        params = {"receipt": "1"} if receipt else None
        body: Dict[str, Any] = {"command": command}
        if value is not None:
            body["value"] = value
        _, data = await self._request(
            "POST",
            f"/api/v1/device/overrides/{quote(key, safe='')}/command",
            params=params,
            json_body=body,
        )
        return _parse(CommandResult.from_dict, data)

    async def set_mode(self, mode: str, *, receipt: bool = False) -> CommandResult:
        """Convenience wrapper: flip the device's operating mode.

        Equivalent to ``send_override_command("mode", mode, receipt=receipt)``.
        """
        return await self.send_override_command("mode", mode, receipt=receipt)

    async def get_override_metadata(self) -> List[OverrideMetadataEntry]:
        """``GET /api/v1/device/overrides/metadata`` -- overridable outputs.

        Fetch and cache this before sending overrides; it changes only when
        the device is reconfigured, not on every poll.
        """
        _, data = await self._request("GET", "/api/v1/device/overrides/metadata")
        return _parse(
            lambda body: [OverrideMetadataEntry.from_dict(item) for item in body], data
        )

    # ------------------------------------------------------------------
    # Log Data
    # ------------------------------------------------------------------

    async def query_logs(
        self,
        start: int,
        end: int,
        *,
        resolution: str = "10m",
        names: Optional[List[str]] = None,
    ) -> LogQueryResult:
        """``GET /api/v1/device/logs`` -- query recorded log history."""
        params: Dict[str, Any] = {"start": start, "end": end, "resolution": resolution}
        if names:
            params["name"] = ",".join(names)
        _, data = await self._request("GET", "/api/v1/device/logs", params=params)
        return _parse(LogQueryResult.from_dict, data)

    async def discover_log_series(
        self,
        *,
        start: Optional[int] = None,
        end: Optional[int] = None,
        resolution: str = "10m",
    ) -> LogSeriesDiscovery:
        """``GET /api/v1/device/logs/series`` -- discover known series."""
        params = {"start": start, "end": end, "resolution": resolution}
        _, data = await self._request("GET", "/api/v1/device/logs/series", params=params)
        return _parse(LogSeriesDiscovery.from_dict, data)

    async def export_logs(
        self,
        start: int,
        end: int,
        *,
        resolution: str = "10m",
        names: Optional[List[str]] = None,
        format: str = "csv",
        timezone: str = "UTC",
    ) -> LogExportResult:
        """``GET /api/v1/device/logs/export`` -- request a downloadable export.

        Returns a signed URL valid for ~15 minutes; the underlying file
        expires after one day. Treat the URL as a bearer credential.
        """
        params: Dict[str, Any] = {
            "start": start,
            "end": end,
            "resolution": resolution,
            "format": format,
            "timezone": timezone,
        }
        if names:
            params["name"] = ",".join(names)
        _, data = await self._request("GET", "/api/v1/device/logs/export", params=params)
        return _parse(LogExportResult.from_dict, data)

    async def download_export(self, export: LogExportResult) -> bytes:
        """Fetch the file referenced by a ``LogExportResult.url``.

        Enforces HTTPS since the URL is a bearer credential.
        """
        if not export.url.startswith("https://"):
            raise HydrosAPIError(f"Export URL must use HTTPS (got {export.url[:40]!r}...)")
        session = self._ensure_session()
        with _wrap_transport_errors(self._timeout.total):
            async with session.get(export.url, timeout=self._timeout) as resp:
                status = resp.status
                body = await resp.read()
        if status >= 400:
            raise HydrosAPIError(
                f"Failed to download export (HTTP {status})", status_code=status
            )
        return body

    async def get_dosing_totals_today(
        self,
        names: List[str],
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, float]:
        """Convenience: total dosed mL per named doser output since local midnight.

        Replicates the "today's dosing total" sensor the old MQTT-based
        ha-hydros integration maintained itself (accumulating dose events
        per day). ``names`` should be doser output names -- override
        metadata entries whose ``commands`` include ``"dose"`` (see
        ``get_override_metadata``).

        Queries ``query_logs(resolution="events")`` from local midnight to
        ``now`` and sums each series with ``LogSeries.total_dose_ml``.
        "Today" is a local-calendar-day concept, so pass ``now`` (defaults
        to ``datetime.now().astimezone()``) to control the reference
        time/timezone explicitly rather than relying on the system one.

        Returns ``0.0`` for any requested name with no events today,
        including when the whole query comes back empty.
        """
        if not names:
            return {}
        reference = now or datetime.now().astimezone()
        start_of_day = reference.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ms = int(start_of_day.timestamp() * 1000)
        end_ms = int(reference.timestamp() * 1000)
        result = await self.query_logs(start_ms, end_ms, resolution="events", names=names)
        return {
            name: result.series[name].total_dose_ml if name in result.series else 0.0
            for name in names
        }


def _extract_session_id(poll_url: str) -> str:
    """Extract the ``id`` query value from a session's ``pollUrl``.

    The spec requires using ``pollUrl`` verbatim rather than constructing it,
    but the client still needs the bare id to pass alongside the poll token
    since the URL's host/path are not assumed to be stable.
    """
    if "id=" not in poll_url:
        raise HydrosAPIError(f"pollUrl is missing the required 'id' parameter: {poll_url!r}")
    return poll_url.rsplit("id=", 1)[-1].split("&", 1)[0]
