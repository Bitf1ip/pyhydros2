# PyHydros2

Async Python client for the official [HYDROS Public API](https://developers.api.coralvuehydros.com/public-api.html) (CoralVue).

This is a ground-up rewrite, **not** a drop-in replacement for [`pyhydros`](../pyhydros). The original library spoke AWS Cognito + MQTT to Hydros' internal cloud; this one speaks CoralVue's official REST API using simple provider/device API keys. There is no AWS SDK dependency at all.

## Why async-only

Home Assistant (and most modern Python services) run on asyncio. The old `pyhydros` was synchronous, which forced [`ha-hydros`](../ha-hydros) to wrap every call in an executor job. `pyhydros2` is built on `aiohttp` from the start, so a future Home Assistant integration can `await` it directly from a `DataUpdateCoordinator` without executor-job wrapping.

## Installation

```bash
pip install -e .
```

## Getting credentials

1. Request a **provider key** from CoralVue: <https://www.coralvuehydros.com/api/#request-provider-key>
2. Have the device owner create a **device key** in the HYDROS app (Device Properties → Manage API Keys), choosing a permission level (read or read & write).

Both values are secrets and must not be committed to source control or embedded in client-side code.

## Quick start

```python
import asyncio
from pyhydros2 import HydrosClient

async def main():
    async with HydrosClient(provider_key="...", device_key="...") as client:
        device = await client.get_device()
        print(device.friendly_name, device.type)

        overrides_metadata = await client.get_override_metadata()
        for entry in overrides_metadata:
            print(entry.key, entry.name, entry.type)

asyncio.run(main())
```

## Polling device state

The state endpoint requires a short-lived poll token obtained from a separate session endpoint. `DeviceStatePoller` manages that lifecycle (start, renew, poll):

```python
from pyhydros2 import HydrosClient, DeviceStatePoller

async def main():
    async with HydrosClient(provider_key="...", device_key="...") as client:
        poller = DeviceStatePoller(client)
        state = await poller.async_poll()  # starts a session automatically
        if state is not None:
            print(state.mode, state.temperature_celsius)

        # Or run continuously at the server-recommended interval:
        async def on_state(state):
            if state is not None:
                print(state.mode)

        await poller.run(on_state)  # runs until you stop it externally
```

`poller.async_poll()` matches the signature a Home Assistant `DataUpdateCoordinator._async_update_data` callback would call directly.

By default the poller uses the server's `pollIntervalSeconds` recommendation from the session response, which is often more conservative than the documented rate limit. Pass `poll_interval_seconds` to poll as fast as the API allows instead:

```python
from pyhydros2.const import STATE_POLL_MIN_INTERVAL_SECONDS  # 6 seconds == 10 req/min

poller = DeviceStatePoller(client, poll_interval_seconds=STATE_POLL_MIN_INTERVAL_SECONDS)
```

Values below the documented floor raise `HydrosConfigError` since they would always eventually hit a 429.

The device state document is treated as **opaque JSON** (per the API's own compatibility guarantees). `DeviceState` exposes convenience properties for commonly-documented fields (`mode`, `inputs`, `outputs`, `health`, `temperature_celsius`, ...) plus `.get(key, default)` / `.raw` for everything else. Its shape is not guaranteed to stay fixed across firmware versions.

Several output/input fields are packed integers rather than ready-to-use values. `DeviceState` provides converted, float accessors for the documented ones:

```python
state.output_percent("Return Left")         # valueState 0-10000  -> 0.0-100.0 (%), for level-type outputs
state.output_on("Heater 1")                 # valueState 0/10000  -> False/True, for bool/flag-type outputs
state.output_voltage_volts("Return Left")   # voltageI (hundredths of a volt) -> volts
state.output_current_amps("Return Left")    # current (milliamps) -> amps
state.output_power_watts("Return Left")     # powerI (tenths of a watt) -> watts
state.output_frequency_hz("Return Left")    # frequency (hundredths of a hertz, undocumented) -> hertz
state.input_triple_level_label("ATO Level") # senseValue 0/1/2 -> "Dry"/"Wet"/"Overflow", for enum-sensorType inputs
state.input_on("Tank Leak")                 # senseValue 0/1     -> False/True, for bool-sensorType inputs
```

`valueState` means different things depending on the output's type: for `level` outputs (variable pumps, dimmed lights) it's a 0-100% position, use `output_percent`; for `bool`/`flag` outputs (heaters, pumps, dosers) it's just on/off, use `output_on` instead. The output's type comes from `get_override_metadata()` (matched by name), not the state document itself. `output_on` is generic: any nonzero `valueState` counts as on, so it also serves as a running/not-running indicator on `level` outputs alongside `output_percent`'s finer-grained value.

`frequency` (seen on mains-powered outputs alongside `voltageI`/`current`/`powerI`) isn't in the spec's documented field list at all -- its hundredths-of-a-hertz scale is inferred from live data (raw values around 5900-6000 line up with 59-60 Hz AC mains), not spec-guaranteed.

The state document doesn't self-describe an input's sensor type, but `discover_log_series()` (`GET /api/v1/device/logs/series`) does, via each series' `sensor_type` (matched by name against `state.inputs`): `enum` means a tri-state float switch, use `input_triple_level_label`; `bool` means a true binary sensor such as a leak detector, use `input_on` instead. Naming can be misleading here -- an input named "Tank Level" may actually be `sensorType: enum` (an overflow-style tri-state switch, firmware type code `Ovf`), not a simple on/off reading, while an input named "Tank Leak" may be the genuine `sensorType: bool` binary leak sensor (firmware type code `Lek`). `sensor_type`, not the name, determines which accessor applies. `analog` inputs (temperature, pH, flow, ...) are already plain numeric readings in the state document and need no further mapping. The underlying conversions (`pyhydros2.units`) are also exported standalone for anything not wrapped by `DeviceState` yet (e.g. `health` entries, which share the same `voltageI`/`current`/`powerI`/`temperatureI` encodings).

### Combined alert status

The old pyhydros/ha-hydros integration exposed a "Collective Alerts" sensor combining every active alert across all inputs and outputs, reporting "Normal" otherwise. `DeviceState` exposes equivalent methods:

```python
state.alerts()         # ["Alky Alkalinity: Value 7.24 dKH out of safe range", "AWC: Max Off Time has been exceeded"]
state.alert_summary()  # "Alky Alkalinity: Value 7.24 dKH out of safe range | AWC: Max Off Time has been exceeded"
                        # or "Normal" when nothing is alerting
```

Every input's `alert` field and every output's `alert`, `drainalert`, and `fillalert` fields (dual-state outputs like an auto water changer track drain/fill sides separately) are scanned; empty strings are ignored.


### Session persistence (surviving restarts)

`DeviceStatePoller` does not cache sessions to disk; persistence is left to the caller. It provides two hooks:

```python
poller = DeviceStatePoller(
    client,
    initial_session=load_previously_persisted_session(),  # e.g. from a file or HA config entry storage; may be None
    on_session_change=persist_session,                     # called whenever a session is started or renewed
)
```

`POST /api/v1/device/state/session` is capped at **5 starts/hour per device** and a session is valid for **6 hours**; a process that restarts often (development, or a future Home Assistant reload) exhausts that quota unnecessarily if it always starts a fresh session. `examples/demo.py` implements a tmp-file-backed cache using this pattern (see `_session_cache_path` / `_load_cached_session` / `_save_cached_session`), and a future HA integration would do the same via config-entry storage.

## Overrides (controlling outputs)

```python
async def main():
    async with HydrosClient(provider_key="...", device_key="...") as client:
        metadata = await client.get_override_metadata()
        return_pump = next(e for e in metadata if e.name == "Return Left")

        # Set a level output to 75%
        await client.put_overrides({return_pump.key: 7500})

        # Clear it (return to schedule)
        await client.delete_override(return_pump.key)

        # Flip operating mode
        await client.set_mode("Feeding")

        # Momentary command (e.g. manual dose)
        await client.send_override_command(some_doser_key, "dose", value=250)
```

Always fetch `get_override_metadata()` before constructing override requests — keys are opaque UUIDs assigned by the device and must not be guessed or derived from output names.

## Log data

```python
async def main():
    async with HydrosClient(provider_key="...", device_key="...") as client:
        result = await client.query_logs(start_ms, end_ms, resolution="10m")
        series = await client.discover_log_series()
        export = await client.export_logs(start_ms, end_ms, format="csv")
        csv_bytes = await client.download_export(export)
```

### Dosing history

The original pyhydros/ha-hydros fetched dosing history from a separate private endpoint. The public API exposes the same data through the log endpoints above: a doser output (override metadata `type: flag` with a `dose` command) logs an `event`-sensorType series whose `valueString` messages look like `"Dose NO3 Dosed 1.0 ml"` (scheduled) or `"Manual Dosed 1.0 ml"` (manual):

```python
async def main():
    async with HydrosClient(provider_key="...", device_key="...") as client:
        dosers = [e.name for e in await client.get_override_metadata() if "dose" in e.commands]
        totals = await client.get_dosing_totals_today(dosers)
        for name, total_ml in totals.items():
            print(name, total_ml, "mL")
```

`get_dosing_totals_today()` queries from local midnight to now (or a `now` you pass in) and sums each series with `LogSeries.total_dose_ml`, matching the "today's dosing total" sensor the old MQTT-based integration maintained itself. For the raw events (e.g. to show individual dose entries), call `query_logs(..., resolution="events", names=dosers)` directly and use `series.total_dose_ml` / `units.parse_dose_ml(message)` on the result.

`discover_log_series()` also reports `first_seen`/`last_seen` for each doser series, which indicates whether it is active without fetching every event. This is unrelated to the old library's *other* AWS S3 blob (`download_hydros_data`), which held a device's zlib-compressed configuration snapshot rather than dosing history; the public API has no equivalent config-blob endpoint.

The demo script's "Dosing today" section shows a concrete "total dosed today" example: it queries from local midnight to now (`datetime.now().astimezone()`, truncated), since "today" is a local-calendar-day concept, not a UTC one.

## Authentication modes

The API documents two header formats:

- **V1 (simple)** — `Authorization: {provider_key}:{device_key}` — implemented, used by default.
- **V2 (HMAC-signed)** — documented header *shape* only; the canonical signing payload isn't published. `pyhydros2.auth.build_provider_v2_header` raises `NotImplementedError` rather than guessing at security-critical signing logic.

## Demo script (manual smoke test against a real device)

`examples/demo.py` exercises the read-only surface of the library against a real device: the collective and its constituent devices (grouping multi-channel outputs under their parent via override metadata's `parent` field), current overrides, recent logs, and a short window of live state polling. It never calls a write endpoint and is safe to run against a live device.

Credentials are loaded from a `.env` file (never hard-coded or committed):

```bash
cp .env.example .env
$EDITOR .env               # fill in HYDROS_PROVIDER_KEY / HYDROS_DEVICE_KEY
pip install -e ".[demo]"
python examples/demo.py --duration 60   # seconds to poll state for
```

By default the demo polls state every `STATE_POLL_MIN_INTERVAL_SECONDS` (6s) -- the fastest cadence that stays within the documented 10 requests/minute limit on `GET /api/v1/device/state` -- rather than the server's often more conservative `pollIntervalSeconds` recommendation. Override with `--poll-interval` or `HYDROS_POLL_INTERVAL_SECONDS`.

The demo also caches its state-polling session in a tmp file (named after a hash of your device key, never the key itself; written with owner-only permissions since it holds a bearer token) so rerunning it within the session's 6-hour lifetime reuses the same session instead of spending another one of the 5 starts/hour allowed for `POST /api/v1/device/state/session`. Pass `--no-session-cache` to always start fresh.

## Rate limits

All limits are per-device, per-endpoint (see `pyhydros2.const.RATE_LIMITS`). This client does not retry automatically — `HydrosRateLimitError` (HTTP 429) is always transient per the spec; back off and retry. `HydrosAuthError` (401) / `HydrosForbiddenError` (403) are not retryable with the same credentials.

## Exception hierarchy

- `HydrosError` — base for everything, including `HydrosConfigError` for bad local input (e.g. malformed keys).
- `HydrosAPIError` — base for HTTP-level failures; carries `.status_code` and `.payload`.
  - `HydrosBadRequestError` (400), `HydrosAuthError` (401), `HydrosForbiddenError` (403), `HydrosNotFoundError` (404), `HydrosPayloadTooLargeError` (413), `HydrosRateLimitError` (429), `HydrosServerError` (500/502/503).

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Known limitations vs. the old `pyhydros`

The public API is scoped to live state, overrides, and logs; it does not expose device *configuration*. The following have no public-API equivalent:

- **Output/input setpoints & config** — heater on/off temperatures, min/max power + power-alert thresholds, on/off timing windows, excluded modes, input-to-output wiring, sensor calibration offsets, alert-level thresholds, graph ranges.
- **Schedule definitions** — the recurrence rules behind a schedule (time, weekday, repeat interval, dose amount). The live state document's `schedule` field only reports the *name* of the currently active schedule, not its definition.
- **Mode definitions** — per-mode timeout/color/exit-delay configuration.
- **System/Option settings** — display units, LED on/off schedule, alert-notification thresholds, heartbeat timeout.
- **Physical node topology** — the old API listed every node in a collective (e.g. `X4`, `XP8`, `MINNOW`) with friendly names. The public API's `GET /api/v1/device` only returns the single device bound to your device key; the raw node IDs visible in a device state's `health` section have no friendly-name mapping available via the public API.

## ⚠️ Safety Warning & Disclaimer

pyhydros2 is provided "as is" and "with all faults", without warranty of any kind, express or implied. The authors make no representations or guarantees regarding safety, suitability, accuracy, reliability, availability, or fitness for any particular purpose.

This software is not designed, tested, or intended for safety-critical, life-supporting, or fail-safe control systems. Do not rely on this library for life-critical functions (e.g. temperature control, circulation, oxygenation) or for scenarios where equipment failure could result in property damage (e.g. floods, electrical hazards, or fire). Overrides are applied directly to device outputs without firmware-level safety checks — understand the physical implications before sending them.

Use of this software is entirely at your own risk. Improper configuration, software defects, network outages, cloud service changes, or unexpected behavior may result in equipment malfunction, property damage, or loss of aquatic life.

Always validate behavior in a controlled or non-critical environment before enabling automations. For critical functions, use Hydros' native controller features, which are specifically designed with local control, redundancy, and safety safeguards.

In no event shall the authors be liable for any direct, indirect, incidental, special, exemplary, or consequential damages arising from the use of, or inability to use, this software.

Nothing in this project constitutes professional, electrical, or safety advice.

This project is an independent, community-driven effort and is not affiliated with, authorized, maintained, or endorsed by CoralVue or Hydros. "Hydros" and "CoralVue" are trademarks of their respective owners and are used for identification purposes only.

## License

MIT — see [LICENSE](LICENSE).
