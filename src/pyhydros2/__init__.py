"""pyhydros2: async Python client for the official HYDROS Public API.

Unlike the original ``pyhydros`` (AWS Cognito + MQTT), this library talks to
CoralVue's official REST API (https://developers.api.coralvuehydros.com)
using provider/device API keys. It is async-only (``aiohttp``) so it can be
awaited directly from Home Assistant or any other asyncio application
without executor-job wrapping.
"""

from __future__ import annotations

from .client import HydrosClient
from .exceptions import (
    HydrosAPIError,
    HydrosAuthError,
    HydrosBadRequestError,
    HydrosConfigError,
    HydrosError,
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
    LogSeries,
    LogSeriesDiscovery,
    LogSeriesInfo,
    OverrideCommandSpec,
    OverrideMetadataEntry,
    OverrideOutputState,
    OverrideState,
    Receipt,
    SessionResponse,
)
from .poller import DeviceStatePoller

__version__ = "2.0.0"

__all__ = [
    "__version__",
    "HydrosClient",
    "DeviceStatePoller",
    # Exceptions
    "HydrosError",
    "HydrosConfigError",
    "HydrosAPIError",
    "HydrosBadRequestError",
    "HydrosAuthError",
    "HydrosForbiddenError",
    "HydrosNotFoundError",
    "HydrosPayloadTooLargeError",
    "HydrosRateLimitError",
    "HydrosServerError",
    # Models
    "Device",
    "DeviceState",
    "SessionResponse",
    "Receipt",
    "OverrideOutputState",
    "OverrideState",
    "OverrideCommandSpec",
    "OverrideMetadataEntry",
    "CommandResult",
    "LogSeries",
    "LogQueryResult",
    "LogSeriesInfo",
    "LogSeriesDiscovery",
    "LogExportResult",
]
