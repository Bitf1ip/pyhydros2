"""Tests for pyhydros2.models."""

from __future__ import annotations

from datetime import timezone

from pyhydros2 import Device, DeviceState, OverrideState, SessionResponse
from pyhydros2.models import LogSeries, OverrideMetadataEntry


def test_device_from_dict():
    device = Device.from_dict(
        {
            "deviceId": "a0b765227294",
            "friendlyName": "Display Tank Controller",
            "type": "X4",
            "owner": "user@example.com",
            "shared": False,
        }
    )
    assert device.device_id == "a0b765227294"
    assert device.friendly_name == "Display Tank Controller"
    assert device.shared is False


def test_session_response_parses_expires_at():
    session = SessionResponse.from_dict(
        {
            "pollUrl": "https://api.coralvuehydros.com/api/v1/device/state?id=abc",
            "pollToken": "token123",
            "durationSeconds": 21600,
            "pollIntervalSeconds": 30,
            "expiresAt": "2026-06-27T02:47:01Z",
        }
    )
    assert session.expires_at.tzinfo is not None
    assert session.expires_at.astimezone(timezone.utc).year == 2026
    assert session.poll_interval_seconds == 30


def test_device_state_exposes_common_fields():
    state = DeviceState.from_dict(
        {
            "mode": "Normal",
            "collectiveStatus": 4,
            "temperatureI": 275,
            "version": "Quatro-380",
            "Input": {"Temperature 1": {"senseValue": 25.875}},
            "Output": {"Return Left": {"valueState": 7500}},
        }
    )
    assert state.mode == "Normal"
    assert state.collective_status == 4
    assert state.temperature_celsius == 34.375
    assert state.inputs["Temperature 1"]["senseValue"] == 25.875
    assert state.outputs["Return Left"]["valueState"] == 7500
    assert state.get("version") == "Quatro-380"
    assert state.get("missing", "default") == "default"


def test_log_series_total_dose_ml_sums_parsed_events():
    series = LogSeries.from_dict(
        "Dosing Pump 1",
        {
            "type": "Dos",
            "sensorType": "event",
            "points": [
                [1000, 1, "Dose NO3 Dosed 1.0 ml"],
                [2000, 1, "Manual Dosed 2.5 ml"],
                [3000, 1, ""],
            ],
        },
    )
    assert series.total_dose_ml == 3.5


def test_log_series_total_dose_ml_empty_is_zero():
    series = LogSeries.from_dict("Dosing Pump 1", {"type": "Dos", "sensorType": "event", "points": []})
    assert series.total_dose_ml == 0.0


def test_device_state_output_unit_conversions():
    state = DeviceState.from_dict(
        {
            "Output": {
                "Return Left": {
                    "valueState": 7500,
                    "voltageI": 2341,
                    "current": 1177,
                    "powerI": 275,
                },
            },
        }
    )
    assert state.output_percent("Return Left") == 75.0
    assert state.output_voltage_volts("Return Left") == 23.41
    assert state.output_current_amps("Return Left") == 1.177
    assert state.output_power_watts("Return Left") == 27.5
    assert state.output_frequency_hz("Return Left") is None
    assert state.output_on("Return Left") is True
    assert state.output_percent("missing") is None


def test_device_state_output_frequency():
    state = DeviceState.from_dict(
        {"Output": {"Heater 1": {"frequency": 5989}}},
    )
    assert state.output_frequency_hz("Heater 1") == 59.89
    assert state.output_frequency_hz("missing") is None


def test_device_state_output_on():
    state = DeviceState.from_dict(
        {"Output": {"Heater 1": {"valueState": 10000}, "Skimmer-Power": {"valueState": 0}}},
    )
    assert state.output_on("Heater 1") is True
    assert state.output_on("Skimmer-Power") is False
    assert state.output_on("missing") is None


def test_device_state_input_triple_level_label():
    state = DeviceState.from_dict(
        {"Input": {"ATO Level": {"senseValue": 2}}},
    )
    assert state.input_triple_level_label("ATO Level") == "Overflow"
    assert state.input_triple_level_label("missing") is None


def test_device_state_input_on():
    state = DeviceState.from_dict(
        {"Input": {"Tank Leak": {"senseValue": 1}, "WC Station": {"senseValue": 0}}},
    )
    assert state.input_on("Tank Leak") is True
    assert state.input_on("WC Station") is False
    assert state.input_on("missing") is None


def test_device_state_alerts_none():
    state = DeviceState.from_dict(
        {
            "Input": {"PH": {"probeValue": 8.0, "alert": ""}},
            "Output": {"Return Left": {"valueState": 7500, "alert": ""}},
        }
    )
    assert state.alerts() == []
    assert state.alert_summary() == "Normal"


def test_device_state_alerts_collected():
    state = DeviceState.from_dict(
        {
            "Input": {
                "Alky Alkalinity": {
                    "value": 7.236,
                    "alert": "Value 7.24 dKH out of safe range",
                },
                "PH": {"probeValue": 8.0, "alert": ""},
            },
            "Output": {
                "Return Left": {"valueState": 7500, "alert": ""},
                "AWC": {
                    "valueState": 0,
                    "alert": "Max Off Time has been exceeded",
                    "drainalert": "",
                    "fillalert": "Fill valve stuck",
                },
            },
        }
    )
    assert state.alerts() == [
        "Alky Alkalinity: Value 7.24 dKH out of safe range",
        "AWC: Max Off Time has been exceeded",
        "AWC (fill): Fill valve stuck",
    ]
    assert state.alert_summary() == (
        "Alky Alkalinity: Value 7.24 dKH out of safe range | "
        "AWC: Max Off Time has been exceeded | "
        "AWC (fill): Fill valve stuck"
    )


def test_device_state_tolerates_missing_sections():
    state = DeviceState.from_dict({"mode": "Feeding"})
    assert state.inputs == {}
    assert state.outputs == {}
    assert state.health == {}
    assert state.temperature_celsius is None


def test_override_state_from_dict_pending():
    state = OverrideState.from_dict(
        {
            "status": "pending",
            "updatedAt": 1693879108136,
            "overrides": {
                "5e6f7a8b-9c0d-4e1f-2a3b-4c5d6e7f8a9b": {
                    "name": "Heaters",
                    "desired": False,
                    "reported": None,
                }
            },
        }
    )
    assert state.pending is True
    assert state.delivered is False
    entry = state.overrides["5e6f7a8b-9c0d-4e1f-2a3b-4c5d6e7f8a9b"]
    assert entry.name == "Heaters"
    assert entry.desired is False
    assert entry.reported is None


def test_override_metadata_entry_mode_type():
    entry = OverrideMetadataEntry.from_dict(
        {
            "key": "mode",
            "name": "Mode",
            "type": "mode",
            "commands": {"Feeding": {}, "Normal": {}, "Water Change": {}},
        }
    )
    assert entry.is_mode is True
    assert "Feeding" in entry.commands
    assert entry.commands["Feeding"].is_parameterized is False


def test_override_metadata_entry_parameterized_command():
    entry = OverrideMetadataEntry.from_dict(
        {
            "key": "abc",
            "name": "iV Tester",
            "type": "bool",
            "commands": {
                "dose": {"label": "Manual Dose", "arg": {"min": 1, "max": 10000, "unit": "0.1 mL"}}
            },
        }
    )
    dose = entry.commands["dose"]
    assert dose.is_parameterized is True
    assert dose.arg_min == 1
    assert dose.arg_max == 10000
    assert dose.arg_unit == "0.1 mL"
