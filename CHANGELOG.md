# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-10-03

### Added

- `DeviceState.output_reservoir_ml` accessor for a dosing pump output's
  remaining reservoir volume.
- `DeviceState.output_overridden` accessor for whether an output currently
  has an active manual override (vs. running on its automatic schedule).
- `DeviceState.mode_timeout_seconds` accessor for the time left on a timed
  operating mode such as Water Change (from the undocumented `timeout`
  field, in milliseconds; absent when no timer is running).
- `HydrosConnectionError` (a `HydrosAPIError` subclass) for network
  failures and timeouts, which previously escaped as raw `aiohttp` /
  `asyncio.TimeoutError` exceptions.

### Changed

- `HydrosClient` rejects non-HTTPS `base_url`s with `HydrosConfigError`,
  since the API keys are sent on every request.
- Malformed or non-JSON success responses raise `HydrosAPIError` instead of
  a bare `KeyError`/`TypeError`/`IndexError`.
- `DeviceState` accessors treat unexpected shapes in the opaque state
  document (e.g. a non-object output entry) as missing instead of raising.
- `SessionResponse.poll_token` and `LogExportResult.url` are excluded from
  `repr()` so they don't leak into logs.
- `LogSeries.total_dose_ml` ignores points without a message instead of
  raising.

## [2.0.0] - 2026-09-30

### Added

- Initial release: async `HydrosClient` for the official HYDROS Public API
  (device info, override metadata, overrides, log queries/export, mode
  control).
- `DeviceStatePoller` for managing the state-polling session lifecycle
  (start, renew, poll) with optional session persistence hooks.
- `DeviceState` convenience accessors for packed/encoded fields (output
  percent/on/voltage/current/power/frequency, input triple-level/on,
  combined alert summary).
- `pyhydros2.units` conversion helpers, usable standalone.
- `examples/demo.py` read-only smoke-test script.
