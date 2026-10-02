"""Typed models for the HYDROS Public API schemas.

The device *state* document is intentionally treated as opaque JSON (the
spec explicitly does not lock its shape as part of the v1 contract), so
``DeviceState`` wraps the raw mapping with convenience accessors instead of
a rigid dataclass. Everything else in the spec is a stable, documented
schema and is modeled with ``dataclasses``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Union

from . import units

OverrideValue = Union[bool, int, None]


@dataclass(frozen=True)
class Device:
    """A device bound to a device key (``GET /api/v1/device``)."""

    device_id: str
    friendly_name: str
    type: str
    owner: str
    shared: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Device":
        return cls(
            device_id=data["deviceId"],
            friendly_name=data["friendlyName"],
            type=data["type"],
            owner=data["owner"],
            shared=bool(data.get("shared", False)),
        )


@dataclass(frozen=True)
class SessionResponse:
    """Response from ``POST /api/v1/device/state/session``."""

    poll_url: str
    poll_token: str
    duration_seconds: int
    poll_interval_seconds: int
    expires_at: datetime

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SessionResponse":
        expires_raw = data["expiresAt"]
        # RFC 3339 'Z' suffix isn't accepted by fromisoformat on Python < 3.11.
        expires_at = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        return cls(
            poll_url=data["pollUrl"],
            poll_token=data["pollToken"],
            duration_seconds=data["durationSeconds"],
            poll_interval_seconds=data["pollIntervalSeconds"],
            expires_at=expires_at,
        )


class DeviceState:
    """Opaque device-state snapshot from ``GET /api/v1/device/state``.

    The API explicitly reserves the right to add, remove, or reshape fields
    across firmware versions without an API version change. Prefer ``raw``
    or ``get()`` for anything not exposed below, and always tolerate
    missing fields.
    """

    __slots__ = ("raw",)

    def __init__(self, raw: Mapping[str, Any]) -> None:
        self.raw = dict(raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DeviceState":
        return cls(data)

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    @property
    def mode(self) -> Optional[str]:
        return self.raw.get("mode")

    @property
    def collective_status(self) -> Optional[int]:
        return self.raw.get("collectiveStatus")

    @property
    def collective_master(self) -> Optional[str]:
        return self.raw.get("collectiveMaster")

    @property
    def firmware_version(self) -> Optional[str]:
        return self.raw.get("version")

    @property
    def config_num(self) -> Optional[int]:
        return self.raw.get("configNum")

    @property
    def temperature_celsius(self) -> Optional[float]:
        return units.eighths_celsius_to_celsius(self.raw.get("temperatureI"))

    @property
    def inputs(self) -> Dict[str, Any]:
        return self.raw.get("Input") or {}

    @property
    def outputs(self) -> Dict[str, Any]:
        return self.raw.get("Output") or {}

    @property
    def health(self) -> Dict[str, Any]:
        return self.raw.get("health") or {}

    @property
    def ota_state(self) -> Dict[str, Any]:
        return self.raw.get("otaState") or {}

    def output_percent(self, name: str) -> Optional[float]:
        """Output ``valueState`` as a 0-100 percent (see ``units.raw_level_to_percent``).

        Only meaningful for ``level``-type outputs (per override metadata);
        use ``output_on`` for ``bool``/``flag`` outputs, or alongside
        ``output_percent`` on ``level`` outputs to get a simple running/not
        running indicator (any nonzero ``valueState`` counts as on).
        """
        return units.raw_level_to_percent(self.outputs.get(name, {}).get("valueState"))

    def output_on(self, name: str) -> Optional[bool]:
        """Output ``valueState`` as on/off (see ``units.raw_level_to_on``).

        Generic across output types: ``0`` is off and any other value is on,
        which is the right (only) interpretation for ``bool``/``flag``
        outputs, and also works for ``level`` outputs as a running/not
        running indicator alongside ``output_percent``'s finer-grained value.
        """
        return units.raw_level_to_on(self.outputs.get(name, {}).get("valueState"))

    def output_voltage_volts(self, name: str) -> Optional[float]:
        """Output ``voltageI`` (supply voltage) converted to volts."""
        return units.centivolts_to_volts(self.outputs.get(name, {}).get("voltageI"))

    def output_current_amps(self, name: str) -> Optional[float]:
        """Output ``current`` converted from milliamps to amps."""
        return units.milliamps_to_amps(self.outputs.get(name, {}).get("current"))

    def output_power_watts(self, name: str) -> Optional[float]:
        """Output ``powerI`` converted to watts."""
        return units.deciwatts_to_watts(self.outputs.get(name, {}).get("powerI"))

    def output_frequency_hz(self, name: str) -> Optional[float]:
        """Output ``frequency`` converted to hertz (see ``units.centihertz_to_hertz``)."""
        return units.centihertz_to_hertz(self.outputs.get(name, {}).get("frequency"))

    def output_reservoir_ml(self, name: str) -> Optional[float]:
        """Output ``reservoir`` (remaining liquid, as calibrated in the
        manufacturer's app) in milliliters -- reported as-is, no unit
        conversion needed. Only meaningful for dosing pump outputs.
        """
        value = self.outputs.get(name, {}).get("reservoir")
        return float(value) if value is not None else None

    def output_overridden(self, name: str) -> Optional[bool]:
        """Whether this output currently has an active manual override, as
        opposed to running on its own schedule/automatic logic (the raw
        state document's per-output ``override`` flag).
        """
        value = self.outputs.get(name, {}).get("override")
        return bool(value) if value is not None else None

    def input_on(self, name: str) -> Optional[bool]:
        """Input ``senseValue`` as on/off (see ``units.raw_level_to_on``).

        Meaningful for inputs whose log series ``sensorType`` (from
        ``discover_log_series()``) is ``bool`` -- e.g. a true binary leak
        detector (firmware type code ``Lek``). Don't use this on inputs
        whose ``sensorType`` is ``enum`` (e.g. firmware type code ``Ovf``,
        tri-state Dry/Wet/Overflow float switches, despite names like "Tank
        Level" not making that obvious) -- use ``input_triple_level_label``
        for those instead.
        """
        return units.raw_level_to_on(self.inputs.get(name, {}).get("senseValue"))

    def input_triple_level_label(self, name: str) -> Optional[str]:
        """Label a tri-state float-switch input's ``senseValue`` (Dry/Wet/Overflow).

        Only meaningful for inputs whose log series ``sensorType`` (from
        ``discover_log_series()``) is ``enum`` (firmware type code ``Ovf``)
        -- the state document itself does not self-describe an input's
        sensor type, so applying this to the wrong input will misinterpret
        its value. Use ``input_on`` instead for ``bool``-sensorType inputs
        like true leak detectors (firmware type code ``Lek``).
        """
        return units.triple_level_label(self.inputs.get(name, {}).get("senseValue"))

    def alerts(self) -> List[str]:
        """Collect every non-empty alert message across all inputs and outputs.

        Scans each input's ``alert`` field and each output's ``alert``,
        ``drainalert``, and ``fillalert`` fields (dual-state outputs such as
        an auto water changer track drain/fill sides separately), formatting
        each as ``"{name}: {message}"`` (or ``"{name} (drain): {message}"`` /
        ``"{name} (fill): {message}"`` for the dual-state fields). Returns an
        empty list when nothing is alerting.
        """
        found: List[str] = []
        for name, attrs in self.inputs.items():
            text = str(attrs.get("alert") or "").strip()
            if text:
                found.append(f"{name}: {text}")
        for name, attrs in self.outputs.items():
            for key in ("alert", "drainalert", "fillalert"):
                text = str(attrs.get(key) or "").strip()
                if not text:
                    continue
                label = name if key == "alert" else f"{name} ({key[:-len('alert')]})"
                found.append(f"{label}: {text}")
        return found

    def alert_summary(self) -> str:
        """Combined alert status: ``alerts()`` joined with ``" | "``, or
        ``"Normal"`` when nothing is alerting.

        Mirrors the old pyhydros/ha-hydros combined "Collective Alerts"
        sensor, which showed "Normal" when no input or output had an active
        alert.
        """
        found = self.alerts()
        return " | ".join(found) if found else "Normal"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DeviceState(mode={self.mode!r}, keys={sorted(self.raw)!r})"


@dataclass(frozen=True)
class Receipt:
    """Device-confirmation receipt, present only when ``receipt=1`` was sent."""

    applied: bool
    waited_ms: int
    reason: Optional[str] = None
    device_connected: Optional[bool] = None
    device_code: Optional[int] = None
    device_body: Any = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Receipt":
        device = data.get("device") or {}
        return cls(
            applied=data["applied"],
            waited_ms=data["waitedMs"],
            reason=data.get("reason"),
            device_connected=data.get("deviceConnected"),
            device_code=device.get("code"),
            device_body=device.get("body"),
        )


@dataclass(frozen=True)
class OverrideOutputState:
    """Per-output entry within ``OverrideState.overrides``."""

    name: str
    desired: OverrideValue
    reported: OverrideValue = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverrideOutputState":
        return cls(
            name=data["name"],
            desired=data.get("desired"),
            reported=data.get("reported"),
        )


@dataclass(frozen=True)
class OverrideState:
    """Current override document (``GET``/``PUT``/``DELETE /overrides``)."""

    status: str
    updated_at: int
    overrides: Dict[str, OverrideOutputState] = field(default_factory=dict)
    receipt: Optional[Receipt] = None

    @property
    def pending(self) -> bool:
        return self.status == "pending"

    @property
    def delivered(self) -> bool:
        return self.status == "delivered"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverrideState":
        overrides = {
            key: OverrideOutputState.from_dict(value)
            for key, value in (data.get("overrides") or {}).items()
        }
        receipt_data = data.get("receipt")
        return cls(
            status=data["status"],
            updated_at=data["updatedAt"],
            overrides=overrides,
            receipt=Receipt.from_dict(receipt_data) if receipt_data else None,
        )


@dataclass(frozen=True)
class OverrideCommandSpec:
    """A single command verb an output accepts."""

    label: Optional[str] = None
    arg_min: Optional[int] = None
    arg_max: Optional[int] = None
    arg_unit: Optional[str] = None

    @property
    def is_parameterized(self) -> bool:
        return self.arg_min is not None or self.arg_max is not None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverrideCommandSpec":
        arg = data.get("arg") or {}
        return cls(
            label=data.get("label"),
            arg_min=arg.get("min"),
            arg_max=arg.get("max"),
            arg_unit=arg.get("unit"),
        )


@dataclass(frozen=True)
class OverrideMetadataEntry:
    """Override capability of a single output or channel.

    ``key`` is the stable, opaque identifier to use with ``PUT``/``DELETE``
    ``/overrides`` and the command endpoint -- never derive it from ``name``.
    """

    key: str
    name: str
    type: str
    min: Optional[int] = None
    max: Optional[int] = None
    label: Optional[str] = None
    parent: Optional[str] = None
    commands: Dict[str, OverrideCommandSpec] = field(default_factory=dict)

    @property
    def is_mode(self) -> bool:
        return self.type == "mode"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OverrideMetadataEntry":
        commands = {
            name: OverrideCommandSpec.from_dict(spec)
            for name, spec in (data.get("commands") or {}).items()
        }
        return cls(
            key=data["key"],
            name=data["name"],
            type=data["type"],
            min=data.get("min"),
            max=data.get("max"),
            label=data.get("label"),
            parent=data.get("parent"),
            commands=commands,
        )


@dataclass(frozen=True)
class CommandResult:
    """Response from ``POST /overrides/{key}/command``."""

    command: str
    published: bool
    device_connected: Optional[bool] = None
    value: Optional[int] = None
    receipt: Optional[Receipt] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CommandResult":
        receipt_data = data.get("receipt")
        return cls(
            command=data["command"],
            published=data.get("published", False),
            device_connected=data.get("deviceConnected"),
            value=data.get("value"),
            receipt=Receipt.from_dict(receipt_data) if receipt_data else None,
        )


@dataclass(frozen=True)
class LogSeries:
    """One named series within a ``LogQueryResult``."""

    name: str
    type: str
    sensor_type: str
    points: List[tuple]

    @classmethod
    def from_dict(cls, name: str, data: Mapping[str, Any]) -> "LogSeries":
        return cls(
            name=name,
            type=data["type"],
            sensor_type=data["sensorType"],
            points=[tuple(point) for point in data.get("points", [])],
        )

    @property
    def total_dose_ml(self) -> float:
        """Sum of parsed dose quantities (mL) across all points.

        Only meaningful for ``event``-sensorType doser series (see
        ``units.parse_dose_ml``); points whose ``valueString`` message
        doesn't parse as a dose event are ignored rather than raising.
        Returns ``0.0`` for a series with no points, mirroring the old
        ha-hydros "0.0 mL dosed today (no events)" fallback.
        """
        total = 0.0
        for _timestamp, _value, message in self.points:
            dosed_ml = units.parse_dose_ml(message)
            if dosed_ml is not None:
                total += dosed_ml
        return total


@dataclass(frozen=True)
class LogQueryResult:
    """Response from ``GET /api/v1/device/logs``."""

    thing_name: str
    start: int
    end: int
    resolution: str
    resolution_ms: Optional[int]
    retention_days: int
    points: int
    series: Dict[str, LogSeries] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogQueryResult":
        series = {
            name: LogSeries.from_dict(name, value)
            for name, value in (data.get("series") or {}).items()
        }
        return cls(
            thing_name=data["thingName"],
            start=data["start"],
            end=data["end"],
            resolution=data["resolution"],
            resolution_ms=data.get("resolutionMs"),
            retention_days=data["retentionDays"],
            points=data["points"],
            series=series,
        )


@dataclass(frozen=True)
class LogSeriesInfo:
    """One entry from ``GET /api/v1/device/logs/series``."""

    name: str
    type: str
    sensor_type: str
    first_seen: Optional[int] = None
    last_seen: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogSeriesInfo":
        return cls(
            name=data["name"],
            type=data["type"],
            sensor_type=data["sensorType"],
            first_seen=data.get("firstSeen"),
            last_seen=data.get("lastSeen"),
        )


@dataclass(frozen=True)
class LogSeriesDiscovery:
    """Response from ``GET /api/v1/device/logs/series``."""

    thing_name: str
    resolution: str
    start: Optional[int]
    end: Optional[int]
    series: List[LogSeriesInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogSeriesDiscovery":
        return cls(
            thing_name=data["thingName"],
            resolution=data["resolution"],
            start=data.get("start"),
            end=data.get("end"),
            series=[LogSeriesInfo.from_dict(item) for item in data.get("series", [])],
        )


@dataclass(frozen=True)
class LogExportResult:
    """Response from ``GET /api/v1/device/logs/export``."""

    url: str
    expires_at: int
    format: str
    points: int
    resolution: str
    timezone: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LogExportResult":
        return cls(
            url=data["url"],
            expires_at=data["expiresAt"],
            format=data["format"],
            points=data["points"],
            resolution=data["resolution"],
            timezone=data.get("timezone"),
        )
