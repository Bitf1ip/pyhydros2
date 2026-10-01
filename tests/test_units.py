"""Tests for pyhydros2.units."""

from __future__ import annotations

from pyhydros2 import units


def test_eighths_celsius_to_celsius():
    assert units.eighths_celsius_to_celsius(275) == 34.375


def test_centivolts_to_volts():
    assert units.centivolts_to_volts(2406) == 24.06


def test_milliamps_to_amps():
    assert units.milliamps_to_amps(1177) == 1.177


def test_deciwatts_to_watts():
    assert units.deciwatts_to_watts(216) == 21.6


def test_centihertz_to_hertz():
    assert units.centihertz_to_hertz(5989) == 59.89


def test_raw_level_to_percent():
    assert units.raw_level_to_percent(7500) == 75.0
    assert units.raw_level_to_percent(10000) == 100.0
    assert units.raw_level_to_percent(-5000) == -50.0


def test_raw_level_to_on():
    assert units.raw_level_to_on(0) is False
    assert units.raw_level_to_on(10000) is True
    assert units.raw_level_to_on(1) is True


def test_triple_level_label():
    assert units.triple_level_label(0) == "Dry"
    assert units.triple_level_label(1) == "Wet"
    assert units.triple_level_label(2) == "Overflow"
    assert units.triple_level_label(3) == "3"  # unknown code, no guessing


def test_parse_dose_ml():
    assert units.parse_dose_ml("Dose NO3 Dosed 1.0 ml") == 1.0
    assert units.parse_dose_ml("Manual Dosed 25.5 ml") == 25.5
    assert units.parse_dose_ml("Manual Dosed 1.0 ML") == 1.0  # case-insensitive
    assert units.parse_dose_ml("Reservoir low") is None  # no quantity mentioned
    assert units.parse_dose_ml("") is None
    assert units.parse_dose_ml(None) is None


def test_conversions_pass_through_none():
    assert units.eighths_celsius_to_celsius(None) is None
    assert units.centivolts_to_volts(None) is None
    assert units.milliamps_to_amps(None) is None
    assert units.deciwatts_to_watts(None) is None
    assert units.raw_level_to_percent(None) is None
    assert units.raw_level_to_on(None) is None
    assert units.centihertz_to_hertz(None) is None
    assert units.triple_level_label(None) is None
    assert units.parse_dose_ml(None) is None
