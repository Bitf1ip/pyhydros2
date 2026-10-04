#!/usr/bin/env python3
"""Manual smoke-test / showcase script for pyhydros2.

Exercises the read-only surface of the library against a real HYDROS
device: fetches device info, lists overridable outputs, reads the current
override document, prints the last hour of logs (``--log-hours`` to change
the window), and polls live device state for a short window.

This script never calls any *write* endpoint (no overrides are set, no
commands are sent) so it's safe to run against a live device.

Credentials are never hard-coded: set them in a ``.env`` file (see
``.env.example``) or export them as real environment variables before
running. ``.env`` is git-ignored.

Usage::

    cp .env.example .env
    $EDITOR .env               # fill in your real keys
    pip install -e ".[demo]"
    python examples/demo.py --duration 60

The state-polling session is cached in a tmp file (keyed by a hash of your
device key, never the key itself) so repeated runs within the session's
6-hour lifetime reuse it instead of burning through the API's 5-starts/hour
limit on ``POST /api/v1/device/state/session``. Pass ``--no-session-cache``
to always start a fresh session.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from pyhydros2 import (
    DeviceState,
    DeviceStatePoller,
    HydrosClient,
    HydrosError,
    HydrosRateLimitError,
    LogSeries,
    SessionResponse,
    units,
)
from pyhydros2.const import DEFAULT_BASE_URL, STATE_POLL_MIN_INTERVAL_SECONDS


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--duration",
        type=int,
        default=int(os.environ.get("HYDROS_POLL_DURATION_SECONDS", "120")),
        help="Seconds to poll device state for (default: 120, or "
        "HYDROS_POLL_DURATION_SECONDS from .env)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=int(
            os.environ.get(
                "HYDROS_POLL_INTERVAL_SECONDS", STATE_POLL_MIN_INTERVAL_SECONDS
            )
        ),
        help="Seconds between state polls (default: "
        f"{STATE_POLL_MIN_INTERVAL_SECONDS}, the fastest cadence that stays "
        "within the documented 10 requests/minute limit on "
        "GET /api/v1/device/state). Pass a larger value to defer to a more "
        "conservative cadence instead.",
    )
    parser.add_argument(
        "--no-session-cache",
        action="store_true",
        help="Always start a fresh state-polling session instead of reusing "
        "one cached in a tmp file from a previous run.",
    )
    parser.add_argument(
        "--log-hours",
        type=float,
        default=float(os.environ.get("HYDROS_LOG_HOURS", "1")),
        help="Hours of log history to print (default: 1, or HYDROS_LOG_HOURS "
        "from .env)",
    )
    args = parser.parse_args()
    if args.log_hours <= 0:
        parser.error("--log-hours must be greater than 0")
    return args


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _fmt(value: Optional[float]) -> str:
    """Round a float to 2 decimal places for display; pass through None."""
    return "None" if value is None else f"{value:.2f}"


def _session_cache_path(device_key: str) -> Path:
    """A tmp file path for caching the state-polling session, for debugging.

    Named after a hash of the device key (never the key itself) so multiple
    devices don't collide and the key can't be recovered from the filename.
    The cached file holds a short-lived bearer token (``pollToken``), so
    it's written with owner-only permissions.
    """
    fingerprint = hashlib.sha256(device_key.encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"pyhydros2_demo_session_{fingerprint}.json"


def _load_cached_session(path: Path) -> Optional[SessionResponse]:
    if not path.exists():
        return None
    try:
        return SessionResponse.from_dict(json.loads(path.read_text()))
    except (OSError, ValueError, KeyError) as exc:
        print(f"(ignoring unreadable session cache at {path}: {exc})")
        return None


def _save_cached_session(path: Path, session: SessionResponse) -> None:
    data = {
        "pollUrl": session.poll_url,
        "pollToken": session.poll_token,
        "durationSeconds": session.duration_seconds,
        "pollIntervalSeconds": session.poll_interval_seconds,
        "expiresAt": session.expires_at.isoformat(),
    }
    path.write_text(json.dumps(data))
    path.chmod(0o600)  # contains a bearer token -- restrict to the current user
    print(f"(cached session to {path}, expires at {session.expires_at.isoformat()})")


def _format_metadata_entry(entry) -> str:
    commands = ", ".join(entry.commands) or "-"
    return (
        f"{entry.name!r} (key={entry.key}, type={entry.type}, "
        f"min={entry.min}, max={entry.max}, commands=[{commands}])"
    )


async def _showcase_collectives(client: HydrosClient) -> None:
    """Print the collective bound to this device key and its constituent devices.

    A HYDROS "collective" is the single top-level entity a device key
    resolves to (``GET /api/v1/device``); its individual devices/outputs
    (heaters, pumps, dosers, ...) are exposed via override metadata, with
    multi-channel outputs linked back to their parent device via ``parent``
    (see the API's "Multi-channel outputs" documentation).
    """
    _print_header("Collectives and devices")
    device = await client.get_device()
    entries = await client.get_override_metadata()

    print(
        f"Collective: {device.friendly_name!r} (id={device.device_id}, "
        f"type={device.type}, owner={device.owner}, shared={device.shared})"
    )

    if not entries:
        print("  (no overridable devices reported)")
        return

    children_by_parent: dict[str, list] = {}
    top_level = []
    for entry in entries:
        if entry.parent:
            children_by_parent.setdefault(entry.parent, []).append(entry)
        else:
            top_level.append(entry)

    print("  Devices:")
    for entry in top_level:
        print(f"    - {_format_metadata_entry(entry)}")
        for child in children_by_parent.get(entry.key, []):
            print(f"        - {_format_metadata_entry(child)} (channel of {entry.name!r})")


async def _showcase_current_overrides(client: HydrosClient) -> None:
    _print_header("Current overrides")
    state = await client.get_overrides()
    print(f"status={state.status} updated_at={state.updated_at}")
    if not state.overrides:
        print("(no active overrides)")
        return
    for key, value in state.overrides.items():
        print(f"- {key}: desired={value.desired} reported={value.reported}")


def _format_log_point(series: LogSeries, point: tuple) -> str:
    value = point[1] if len(point) > 1 else None
    message = point[2] if len(point) > 2 else ""
    if series.sensor_type == "bool":
        return "on" if value else "off"
    if series.sensor_type == "enum" and series.type == "Ovf":
        return units.triple_level_label(value) or "None"
    if series.sensor_type == "event":
        return message or str(value)
    return f"{value}  {message}" if message else str(value)


async def _showcase_recent_logs(client: HydrosClient, hours: float) -> None:
    tz_name = datetime.now().astimezone().tzname()
    _print_header(f"Logs for the last {hours:g} hour(s) (local time, {tz_name})")
    # The logs endpoints take epoch milliseconds.
    end = int(time.time() * 1000)
    start = end - int(hours * 3600 * 1000)

    rows: dict[tuple[int, str], tuple[str, str]] = {}
    # "10m" has analog readings plus on/off and level changes; dose events only come back with "events".
    for resolution in ("10m", "events"):
        try:
            result = await client.query_logs(start, end, resolution=resolution)
        except HydrosError as exc:
            print(f"(log query at {resolution!r} resolution failed: {exc})")
            continue
        for name, series in result.series.items():
            for point in series.points:
                rows[(point[0], name)] = (series.type, _format_log_point(series, point))

    if not rows:
        print("(no log entries in this window)")
        return

    width = max(len(f"{name} [{kind}]") for (_, name), (kind, _) in rows.items())
    for (timestamp, name), (kind, text) in sorted(rows.items()):
        when = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{when}  {f'{name} [{kind}]':<{width}}  {text}")
    print(
        f"{len(rows)} entries across {len({name for _, name in rows})} series "
        "(analog values are 10-minute readings; on/off and level changes are exact)"
    )


async def _showcase_dosing_history(client: HydrosClient) -> None:
    _print_header("Dosing today")
    doser_names = [
        entry.name
        for entry in await client.get_override_metadata()
        if "dose" in entry.commands
    ]
    if not doser_names:
        print("(no dosers found in override metadata)")
        return

    now_local = datetime.now().astimezone()
    start_of_day_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = int(start_of_day_local.timestamp() * 1000)
    end = int(now_local.timestamp() * 1000)
    try:
        result = await client.query_logs(start, end, resolution="events", names=doser_names)
    except HydrosError as exc:
        print(f"(log query failed: {exc})")
        return

    for name in doser_names:
        series = result.series.get(name)
        if series is None or not series.points:
            print(f"- {name}: 0.00 mL dosed today (no events)")
            continue
        # LogSeries.total_dose_ml sums parsed dose quantities for you.
        print(f"- {name}: {series.total_dose_ml:.2f} mL dosed today ({len(series.points)} event(s))")
        for timestamp, _value, message in series.points[-3:]:
            print(f"    {timestamp}: {message}")


async def _showcase_state_polling(
    client: HydrosClient,
    duration: int,
    poll_interval: int,
    *,
    session_cache_path: Optional[Path],
) -> None:
    _print_header(
        f"Live state polling for {duration}s (every {poll_interval}s, "
        f"{60 / poll_interval:.2f} req/min)"
    )

    output_types = {entry.name: entry.type for entry in await client.get_override_metadata()}
    input_sensor_types = {
        series.name: series.sensor_type for series in (await client.discover_log_series()).series
    }

    cached_session = _load_cached_session(session_cache_path) if session_cache_path else None
    if cached_session is not None:
        print(f"Reusing cached session from {session_cache_path} "
              f"(expires at {cached_session.expires_at.isoformat()})")
    else:
        print("No usable cached session; a new one will be started "
              "(uses 1 of the 5 allowed per hour).")

    def on_session_change(session: SessionResponse) -> None:
        if session_cache_path is not None:
            _save_cached_session(session_cache_path, session)

    poller = DeviceStatePoller(
        client,
        poll_interval_seconds=poll_interval,
        initial_session=cached_session,
        on_session_change=on_session_change,
    )
    stop_event = asyncio.Event()
    poll_count = 0

    async def on_state(state: DeviceState | None) -> None:
        nonlocal poll_count
        poll_count += 1
        if state is None:
            print(f"[{poll_count}] no state snapshot yet (device offline or never reported)")
            return
        print(f"[{poll_count}] mode={state.mode} temperature_c={_fmt(state.temperature_celsius)}")
        print(f"  alerts: {state.alert_summary()}")
        print("  inputs:")
        for name, attrs in sorted(state.inputs.items()):
            converted = []
            if "senseValue" in attrs:
                sensor_type = input_sensor_types.get(name)
                if sensor_type == "bool":
                    converted.append(f"on={state.input_on(name)}")
                elif sensor_type == "enum":
                    converted.append(f"level={state.input_triple_level_label(name)}")
            suffix = f" ({', '.join(converted)})" if converted else ""
            print(f"    - {name}: {attrs}{suffix}")
        print("  outputs:")
        for name, attrs in sorted(state.outputs.items()):
            converted = []
            if "valueState" in attrs:
                if output_types.get(name) in ("bool", "flag"):
                    converted.append(f"on={state.output_on(name)}")
                else:
                    converted.append(f"percent={_fmt(state.output_percent(name))}")
                    converted.append(f"on={state.output_on(name)}")
            if "voltageI" in attrs:
                converted.append(f"voltage_v={_fmt(state.output_voltage_volts(name))}")
            if "current" in attrs:
                converted.append(f"current_a={_fmt(state.output_current_amps(name))}")
            if "powerI" in attrs:
                converted.append(f"power_w={_fmt(state.output_power_watts(name))}")
            if "frequency" in attrs:
                converted.append(f"frequency_hz={_fmt(state.output_frequency_hz(name))}")
            suffix = f" ({', '.join(converted)})" if converted else ""
            print(f"    - {name}: {attrs}{suffix}")

    runner = asyncio.create_task(poller.run(on_state, stop_event=stop_event))
    await asyncio.sleep(duration)
    stop_event.set()
    await runner
    print(f"Polled {poll_count} time(s) over {duration}s "
          f"(interval={poller.poll_interval_seconds}s)")


async def main() -> int:
    load_dotenv()
    args = _parse_args()

    provider_key = os.environ.get("HYDROS_PROVIDER_KEY")
    device_key = os.environ.get("HYDROS_DEVICE_KEY")
    if not provider_key or not device_key:
        print(
            "Missing credentials. Copy .env.example to .env and fill in "
            "HYDROS_PROVIDER_KEY / HYDROS_DEVICE_KEY, or export them as "
            "environment variables.",
            file=sys.stderr,
        )
        return 1

    base_url = os.environ.get("HYDROS_BASE_URL", DEFAULT_BASE_URL)
    session_cache_path = None if args.no_session_cache else _session_cache_path(device_key)

    async with HydrosClient(provider_key, device_key, base_url=base_url) as client:
        try:
            await _showcase_collectives(client)
            await _showcase_current_overrides(client)
            await _showcase_recent_logs(client, args.log_hours)
            await _showcase_dosing_history(client)
            await _showcase_state_polling(
                client,
                args.duration,
                args.poll_interval,
                session_cache_path=session_cache_path,
            )
        except HydrosRateLimitError as exc:
            print(
                f"\nRate limit hit: {exc}\n"
                "POST /api/v1/device/state/session (used by DeviceStatePoller to start "
                "live state polling) is capped at 5 starts/hour per device. Each run of "
                "this demo starts a fresh session, so rerunning it repeatedly within the "
                "same hour will hit this limit -- wait for the hourly window to reset "
                "before trying again.",
                file=sys.stderr,
            )
            return 1
        except HydrosError as exc:
            print(f"\nHYDROS API error: {exc}", file=sys.stderr)
            return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
