"""Shared constants for the HYDROS Public API client.

Values mirror https://developers.api.coralvuehydros.com/public-api.html
(spec version 1.0.0). Rate limits are informational only -- the server is
always the source of truth and returns HTTP 429 when a limit is exceeded.
"""

from __future__ import annotations

#: Production base URL. There is currently no public sandbox environment.
DEFAULT_BASE_URL = "https://api.coralvuehydros.com"

#: Recommended minimum polling cadence advertised by the API (seconds).
#: The server also returns its own ``pollIntervalSeconds`` per session;
#: prefer that value when available.
DEFAULT_POLL_INTERVAL_SECONDS = 30

#: Fastest cadence (seconds) that stays within the documented
#: ``GET /api/v1/device/state`` rate limit of 10 requests/minute. The
#: server-recommended ``pollIntervalSeconds`` is often more conservative
#: than this; callers that want to fully use the allotted rate can pass
#: this to ``DeviceStatePoller(poll_interval_seconds=...)``.
STATE_POLL_MIN_INTERVAL_SECONDS = 6

#: Poll-session lifetime (seconds) as documented for ``durationSeconds``.
SESSION_DURATION_SECONDS = 21600  # 6 hours

#: Renew a session this many seconds before it expires.
DEFAULT_SESSION_RENEW_MARGIN_SECONDS = 1800  # 30 minutes

#: Valid values for the ``resolution`` query parameter on log endpoints.
LOG_RESOLUTIONS = ("10m", "2h", "1d", "events")

#: Retention window (days) per resolution, as documented.
LOG_RETENTION_DAYS = {
    "10m": 33,
    "2h": 93,
    "1d": 365,
    "events": 93,
}

#: Maximum span, in days, accepted by the logs query/export endpoints.
LOG_MAX_RANGE_DAYS = 366

#: Per-device, per-endpoint rate limits (requests, period_seconds).
#: Informational only -- enforced server-side.
RATE_LIMITS = {
    "GET /api/v1/device": (60, 60),
    "GET /api/v1/device/state": (10, 60),
    "POST /api/v1/device/state/session": (5, 3600),
    "GET /api/v1/device/overrides": (60, 60),
    "PUT /api/v1/device/overrides": (10, 60),
    "DELETE /api/v1/device/overrides/{key}": (10, 60),
    "POST /api/v1/device/overrides/{key}/command": (10, 60),
    "GET /api/v1/device/overrides/metadata": (10, 60),
    "GET /api/v1/device/logs": (20, 60),
    "GET /api/v1/device/logs/series": (20, 60),
    "GET /api/v1/device/logs/export": (6, 3600),
}

#: Reserved override/metadata key representing the device's operating mode.
MODE_KEY = "mode"
