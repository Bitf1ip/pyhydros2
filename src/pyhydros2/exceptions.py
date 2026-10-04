"""Exception hierarchy for the HYDROS Public API client.

Every exception carries the HTTP ``status_code`` (when known) and the raw
``error`` message reported by the API, so callers can log or surface
actionable detail without parsing strings.

Per the API's documented semantics: ``429`` is always transient (back off
and retry); ``401``/``403`` are not (do not retry with the same
credentials).
"""

from __future__ import annotations

from typing import Any, Optional


class HydrosError(Exception):
    """Base exception for all pyhydros2 errors."""


class HydrosConfigError(HydrosError):
    """Raised for invalid client configuration (e.g. malformed keys)."""


class HydrosAPIError(HydrosError):
    """Raised for HTTP-level failures talking to the HYDROS Public API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload

    @property
    def error(self) -> str:
        return str(self)


class HydrosBadRequestError(HydrosAPIError):
    """HTTP 400: invalid request parameters, range, or value."""


class HydrosAuthError(HydrosAPIError):
    """HTTP 401: missing or invalid credentials. Do not retry unchanged."""


class HydrosForbiddenError(HydrosAPIError):
    """HTTP 403: valid credentials but insufficient permission.

    Most commonly a read-scoped device key attempting a write. The key's
    permission level is fixed at creation and retrying will not help.
    """


class HydrosNotFoundError(HydrosAPIError):
    """HTTP 404: device or resource not found / not currently available."""


class HydrosPayloadTooLargeError(HydrosAPIError):
    """HTTP 413: result would exceed the bounded query/export budget."""


class HydrosRateLimitError(HydrosAPIError):
    """HTTP 429: per-device rate limit exceeded. Always transient."""


class HydrosServerError(HydrosAPIError):
    """HTTP 500/502/503: server-side failure; no partial result is returned."""


class HydrosConnectionError(HydrosAPIError):
    """No HTTP response at all: network failure, DNS/TLS error, or timeout. Transient."""
