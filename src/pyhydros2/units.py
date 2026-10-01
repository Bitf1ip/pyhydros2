"""Unit conversions for canonical fields documented in the device state
and log-data schemas. Kept separate from ``models`` so Home Assistant (or
any consumer) can reuse them when mapping raw device-state fields to
sensor values.

All functions return ``None`` when given ``None`` so they compose cleanly
with ``dict.get()`` lookups on the intentionally-opaque state document.
"""

from __future__ import annotations

import re
from typing import Optional

#: Matches a dosed quantity like "1.0 ml" within a dose event's ``valueString``
#: (e.g. "Dose NO3 Dosed 1.0 ml", "Manual Dosed 1.0 ml"). Ported from the
#: original pyhydros MQTT client's ``_DOSE_VALUE_PATTERN``.
_DOSE_ML_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*ml", re.IGNORECASE)

#: Labels for tri-state float-switch inputs (e.g. an ATO or sump level
#: sensor reporting ``senseValue`` 0/1/2). Ported from the original
#: pyhydros MQTT client's ``TRIPLE_LEVEL_LABELS``; the public REST API's
#: state document does not self-describe an input's sensor type, so the
#: caller must know which inputs are tri-state before applying this.
TRIPLE_LEVEL_LABELS = {
    0: "Dry",
    1: "Wet",
    2: "Overflow",
}


def eighths_celsius_to_celsius(value: Optional[int]) -> Optional[float]:
    """Convert ``temperatureI``-style eighths-of-a-degree-C to degrees C."""
    if value is None:
        return None
    return value / 8


def centivolts_to_volts(value: Optional[int]) -> Optional[float]:
    """Convert ``voltageI``-style hundredths-of-a-volt to volts."""
    if value is None:
        return None
    return value / 100


def milliamps_to_amps(value: Optional[int]) -> Optional[float]:
    """Convert ``current``-style milliamps to amps."""
    if value is None:
        return None
    return value / 1000


def deciwatts_to_watts(value: Optional[int]) -> Optional[float]:
    """Convert ``powerI``-style tenths-of-a-watt to watts."""
    if value is None:
        return None
    return value / 10


def centihertz_to_hertz(value: Optional[int]) -> Optional[float]:
    """Convert an output's ``frequency``-style hundredths-of-a-hertz to hertz.

    ``frequency`` isn't in the documented state-document field list (the
    spec only promises the document is guidance, not a locked contract);
    this scale is inferred from live data -- raw values around 5900-6000
    line up with 59-60 Hz AC mains once divided by 100.
    """
    if value is None:
        return None
    return value / 100


def raw_level_to_percent(value: Optional[int]) -> Optional[float]:
    """Convert an output's ``valueState`` (raw 0-10000 range) to a 0-100 percent.

    Per the state document's documented convention, ``valueState`` is
    "normally 0-10000 where 10000 is full on"; reversible outputs may report
    negative values, which convert to a negative percent here.
    """
    if value is None:
        return None
    return value / 100


def raw_level_to_on(value: Optional[int]) -> Optional[bool]:
    """Interpret a raw integer reading as on/off: ``0`` is off, any other
    value (commonly ``1`` or ``10000``) is on.

    Works generically on both output ``valueState`` and input ``senseValue``
    readings. For ``bool``/``flag``-type outputs and ``bool``-sensorType
    inputs (e.g. a leak detector) this is the only meaningful reading. For
    ``level``-type outputs it still works as a running/not-running
    indicator, complementing the finer-grained ``raw_level_to_percent``.
    An output's type comes from override metadata
    (``GET /api/v1/device/overrides/metadata``); an input's sensor type
    comes from log series discovery (``GET /api/v1/device/logs/series``,
    ``sensorType`` field); the state document itself doesn't say either.
    """
    if value is None:
        return None
    return value != 0


def triple_level_label(value: Optional[int]) -> Optional[str]:
    """Map a tri-state float-switch ``senseValue`` to its label.

    Returns ``None`` when ``value`` is ``None``, and the raw value's string
    form (rather than raising) for any code outside ``TRIPLE_LEVEL_LABELS``,
    since the state document does not guarantee firmware won't add states.
    """
    if value is None:
        return None
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value)
    return TRIPLE_LEVEL_LABELS.get(index, str(index))


def parse_dose_ml(message: Optional[str]) -> Optional[float]:
    """Extract a dosed quantity in mL from a dose event's ``valueString``.

    Doser outputs (override metadata ``type: flag`` entries with a ``dose``
    command) log ``event``-sensorType series (see ``discover_log_series()``
    / ``query_logs()``) whose ``valueString`` messages look like
    ``"Dose NO3 Dosed 1.0 ml"`` (scheduled) or ``"Manual Dosed 1.0 ml"``
    (manual). Returns ``None`` if ``message`` is ``None``/empty or doesn't
    mention a quantity in mL.
    """
    if not message:
        return None
    match = _DOSE_ML_PATTERN.search(message)
    if not match:
        return None
    return float(match.group(1))

