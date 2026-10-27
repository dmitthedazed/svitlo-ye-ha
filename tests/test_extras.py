"""Tests for the event entity, button, service, repairs and reconfigure."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.svitlo_ye.const import DOMAIN, FAILURES_BEFORE_ISSUE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .conftest import FROZEN_NOW, mock_schedule
from .test_init import setup, state


@pytest.fixture(autouse=True)
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at 12:00 Kyiv."""
    freezer.move_to(FROZEN_NOW)
    return freezer


async def test_next_power_sensors_and_tomorrow(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Next power off is 13:00 Kyiv; tomorrow is not published."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    assert state(hass, "sensor", "next_power_off").state.startswith("2026-10-27T11:00")
    assert state(hass, "sensor", "next_power_on").state not in ("unknown", "unavailable")
    assert state(hass, "binary_sensor", "tomorrow_published").state == "off"


async def test_event_on_power_change(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen: FrozenDateTimeFactory,
) -> None:
    """The event entity fires power_off when the outage starts."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    assert state(hass, "event", "schedule_event").state == "unknown"

    frozen.move_to("2026-10-27T11:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    event = state(hass, "event", "schedule_event")
    assert event.attributes["event_type"] == "power_off"


async def test_refresh_button(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Pressing the button fetches the schedule again."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    calls = aioclient_mock.call_count
    entity_id = state(hass, "button", "refresh").entity_id
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    assert aioclient_mock.call_count > calls


async def test_get_schedule_service(
    hass: HomeAssistant, config_entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """The service returns intervals per day."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    entity_id = state(hass, "sensor", "schedule").entity_id
    response = await hass.services.async_call(
        DOMAIN,
        "get_schedule",
        {"entity_id": entity_id, "days": 2},
        blocking=True,
        return_response=True,
    )
    result = response[entity_id]
    assert result["queue"] == "1.2"
    assert set(result["days"]) == {"2026-10-27", "2026-10-28"}
    assert result["days"]["2026-10-27"]
    assert result["days"]["2026-10-28"] == []


async def test_repair_issue_after_repeated_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen: FrozenDateTimeFactory,
) -> None:
    """A repair issue appears after many failures and disappears on recovery."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    registry = ir.async_get(hass)
    issue_id = f"api_unavailable_{config_entry.entry_id}"

    aioclient_mock.clear_requests()
    mock_schedule(aioclient_mock, exc=TimeoutError())
    for _ in range(FAILURES_BEFORE_ISSUE):
        frozen.tick(timedelta(minutes=16))
        async_fire_time_changed(hass)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    aioclient_mock.clear_requests()
    mock_schedule(aioclient_mock)
    frozen.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert registry.async_get_issue(DOMAIN, issue_id) is None


async def test_reconfigure_flow(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_location_api: AiohttpClientMocker,
) -> None:
    """Reconfigure keeps the unique id and updates the address data."""
    mock_schedule(mock_location_api)
    await setup(hass, config_entry)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"rem_id": "7"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"city_id": "16657"})
    if result["step_id"] == "street_search":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"street_search": ""}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"street_id": "173934"}
    )
    assert result["step_id"] == "house"
    key = result["data_schema"].schema["house"].config["options"][0]["value"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"house": key, "name": "Дім"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.title == "Дім"
    assert config_entry.unique_id == "388680|1|legal"
