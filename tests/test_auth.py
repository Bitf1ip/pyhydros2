"""Tests for pyhydros2.auth."""

from __future__ import annotations

import pytest

from pyhydros2 import HydrosConfigError
from pyhydros2.auth import build_provider_v1_header, build_provider_v2_header


def test_build_provider_v1_header():
    assert build_provider_v1_header("provider_abc", "device_xyz") == "provider_abc:device_xyz"


def test_build_provider_v1_header_strips_whitespace():
    assert build_provider_v1_header(" provider_abc ", " device_xyz ") == "provider_abc:device_xyz"


@pytest.mark.parametrize("provider_key,device_key", [("", "device"), ("provider", ""), ("   ", "device")])
def test_build_provider_v1_header_rejects_empty(provider_key, device_key):
    with pytest.raises(HydrosConfigError):
        build_provider_v1_header(provider_key, device_key)


def test_build_provider_v1_header_rejects_control_characters():
    with pytest.raises(HydrosConfigError):
        build_provider_v1_header("provider\r\nInjected: true", "device")


def test_build_provider_v2_header_not_implemented():
    with pytest.raises(NotImplementedError):
        build_provider_v2_header()
