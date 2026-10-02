# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `DeviceState.output_reservoir_ml` accessor for a dosing pump output's
  remaining reservoir volume.
- `DeviceState.output_overridden` accessor for whether an output currently
  has an active manual override (vs. running on its automatic schedule).

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
