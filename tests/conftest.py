"""Shared fixtures for SvitloYE tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.svitlo_ye.const import (
    BASE_URL,
    CONF_ADDRESS_ID,
    CONF_CHERGA,
    CONF_CITY_ID,
    CONF_CITY_NAME,
    CONF_HOUSE,
    CONF_HOUSE_CATEGORY,
    CONF_PIDCHERGA,
    CONF_REM_ID,
    CONF_REM_NAME,
    CONF_STREET_ID,
    CONF_STREET_NAME,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

FIXTURES = Path(__file__).parent / "fixtures"

# Real responses were captured on 27.10.2026 (Kyiv). 12:00 Kyiv (UTC+2) is inside the
# 10:00-13:00 "power on" interval of queue 1.2; the next outage starts at 13:00.
FROZEN_NOW = "2026-10-27T10:00:00+00:00"

SCHEDULE_UPDATED = {"Last-Modified-Shedules-Date": "2026.10.27 00:16:59"}


def load_text(name: str) -> str:
    """Load a fixture file as text."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_json(name: str) -> Any:
    """Load a fixture file as JSON."""
    return json.loads(load_text(name))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in every test."""


@pytest.fixture(autouse=True)
async def kyiv_time_zone(hass: HomeAssistant) -> None:
    """Run Home Assistant in the schedule's time zone."""
    await hass.config.async_set_time_zone("Europe/Kyiv")


@pytest.fixture
def entry_data() -> dict[str, Any]:
    """Config entry data for queue 1.2."""
    return {
        CONF_REM_ID: "7",
        CONF_REM_NAME: "Житомирський",
        CONF_CITY_ID: "16657",
        CONF_CITY_NAME: "місто Житомир",
        CONF_STREET_ID: "173934",
        CONF_STREET_NAME: "вул. Київська",
        CONF_ADDRESS_ID: "388680",
        CONF_HOUSE: "1",
        CONF_HOUSE_CATEGORY: "legal",
        CONF_CHERGA: 1,
        CONF_PIDCHERGA: 2,
    }


@pytest.fixture
def config_entry(entry_data: dict[str, Any]) -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="вул. Київська, 1",
        unique_id="388680|1|legal",
        data=entry_data,
    )


def mock_schedule(
    aioclient_mock: AiohttpClientMocker,
    schedule: Any | str = "schedule_1_2.json",
    cherga: int = 1,
    pidcherga: int = 2,
    **kwargs: Any,
) -> None:
    """Register schedule + messages responses."""
    url = f"{BASE_URL}api-schedule.php?cherga_id={cherga}&pidcherga_id={pidcherga}"
    if kwargs:
        aioclient_mock.get(url, **kwargs)
    elif isinstance(schedule, str):
        aioclient_mock.get(url, text=load_text(schedule))
    else:
        aioclient_mock.get(url, json=schedule)
    aioclient_mock.get(
        f"{BASE_URL}api-message.php",
        text=load_text("messages.json"),
        headers=SCHEDULE_UPDATED,
    )


@pytest.fixture
def mock_location_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock the REM -> city -> street -> address chain."""
    aioclient_mock.get(f"{BASE_URL}api-rem.php", text=load_text("rem.json"))
    aioclient_mock.get(f"{BASE_URL}api-city.php?rem_id=7", text=load_text("city.json"))
    aioclient_mock.get(f"{BASE_URL}api-street.php?city_id=16657", text=load_text("street.json"))
    aioclient_mock.get(
        f"{BASE_URL}api-address.php?street_id=173934", text=load_text("address.json")
    )
    return aioclient_mock
