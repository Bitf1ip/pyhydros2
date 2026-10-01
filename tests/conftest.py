"""Shared pytest fixtures for pyhydros2 tests."""

from __future__ import annotations

import pytest

from pyhydros2 import HydrosClient

PROVIDER_KEY = "hydros_provider_test"
DEVICE_KEY = "device_test_key"
BASE_URL = "https://api.coralvuehydros.com"


@pytest.fixture
async def client():
    async with HydrosClient(PROVIDER_KEY, DEVICE_KEY, base_url=BASE_URL) as c:
        yield c
