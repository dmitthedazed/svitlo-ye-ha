"""Tests for setup, coordinator behaviour, entities, calendar and diagnostics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.svitlo_ye.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .conftest import FROZEN_NOW, mock_schedule
from .test_schedule import half_hours

UID = "388680|1|legal"


def eid(hass: HomeAssistant, platform: str, key: str) -> str:
    """Return the entity id for a unique id key."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{UID}_{key}")
    assert entity_id, key
    return entity_id


def state(hass: HomeAssistant, platform: str, key: str) -> Any:
    """Return the state object."""
    st = hass.states.get(eid(hass, platform, key))
    assert st is not None
    return st


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the integration."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Freeze time at 12:00 Kyiv on the day of the captured fixtures."""
    freezer.move_to(FROZEN_NOW)
    return freezer


async def test_setup_and_entities(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """All entities are created with the right states at 12:00 Kyiv."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    power = state(hass, "binary_sensor", "power")
    assert power.state == STATE_ON
    # Names come from the translations (has_entity_name + translation_key).
    assert power.attributes["friendly_name"] == "вул. Київська, 1 Power"
    assert (
        state(hass, "sensor", "time_to_change")
        .attributes["friendly_name"]
        .endswith("Time to power change")
    )
    assert state(hass, "calendar", "outages").attributes["friendly_name"].endswith("Outages")
    assert power.attributes["status"] == "available"
    assert power.attributes["current_interval"]["start_time"] == "10:00"
    assert power.attributes["current_interval"]["end_time"] == "13:00"
    assert power.attributes["queue"] == "1.2"

    assert state(hass, "sensor", "schedule").state == "available"
    schedule = state(hass, "sensor", "schedule").attributes
    assert len(schedule["today"]) == 7
    assert schedule["tomorrow"] == []
    assert schedule["messages"][0] == "УВАГА! ВАЖЛИВА ІНФОРМАЦІЯ!"

    assert state(hass, "sensor", "next_change").state == "2026-10-27T11:00:00+00:00"
    assert state(hass, "sensor", "next_change").attributes["next_power_state"] == "off"
    assert state(hass, "sensor", "time_to_change").state == "60"
    assert state(hass, "sensor", "queue").state == "1.2"
    assert float(state(hass, "sensor", "outage_today").state) == 7.0
    assert len(state(hass, "sensor", "outage_today").attributes["outages"]) == 3
    assert state(hass, "sensor", "outage_tomorrow").state == STATE_UNKNOWN
    assert state(hass, "sensor", "last_update").state == "2026-10-26T22:16:59+00:00"

    calendar = state(hass, "calendar", "outages")
    assert calendar.state == STATE_OFF
    assert calendar.attributes["start_time"] == "2026-10-27 13:00:00"

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, UID)}
    assert device.model == "Черга 1.2"
    assert device.name == "вул. Київська, 1"

    entity = er.async_get(hass).async_get(eid(hass, "sensor", "last_update"))
    assert entity is not None
    assert entity.entity_category is er.EntityCategory.DIAGNOSTIC


async def test_minute_tick_flips_state(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen: FrozenDateTimeFactory,
) -> None:
    """At 13:00 Kyiv the outage starts without a new API request."""
    mock_schedule(aioclient_mock)
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=config_entry.title,
        unique_id=config_entry.unique_id,
        data=config_entry.data,
        options={"scan_interval": 180},
    )
    await setup(hass, config_entry)
    calls = aioclient_mock.call_count

    frozen.move_to("2026-10-27T11:00:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert aioclient_mock.call_count == calls
    assert state(hass, "binary_sensor", "power").state == STATE_OFF
    assert state(hass, "sensor", "schedule").state == "outage"
    assert state(hass, "sensor", "time_to_change").state == "180"
    assert state(hass, "calendar", "outages").state == STATE_ON

    # After 21:00 (19:00 UTC) the last interval runs until midnight; tomorrow is
    # not published, so the next change is unknown.
    frozen.move_to("2026-10-27T19:30:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state(hass, "binary_sensor", "power").state == STATE_ON
    assert state(hass, "sensor", "next_change").state == STATE_UNKNOWN
    assert state(hass, "sensor", "time_to_change").state == STATE_UNKNOWN

    # After midnight nothing is published: power state is unknown.
    frozen.move_to("2026-10-27T22:30:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state(hass, "binary_sensor", "power").state == STATE_UNKNOWN
    assert state(hass, "sensor", "schedule").state == "unknown"


async def test_tomorrow_and_midnight(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen: FrozenDateTimeFactory,
) -> None:
    """An outage crossing midnight shows up in both days and the countdown spans it."""
    raw = half_hours("27.10.2026", {(22, 24): "red"}) + half_hours(
        "28.10.2026", {(0, 2): "red", (2, 3): "yellow"}
    )
    mock_schedule(aioclient_mock, raw)
    frozen.move_to("2026-10-27T21:50:00+00:00")  # 23:50 Kyiv
    await setup(hass, config_entry)

    assert state(hass, "binary_sensor", "power").state == STATE_OFF
    # Power returns after the probable outage, at 03:00 Kyiv (01:00 UTC).
    assert state(hass, "sensor", "next_change").state == "2026-10-28T01:00:00+00:00"
    assert state(hass, "sensor", "time_to_change").state == "190"
    assert float(state(hass, "sensor", "outage_today").state) == 2.0
    tomorrow = state(hass, "sensor", "outage_tomorrow")
    assert float(tomorrow.state) == 2.0
    assert tomorrow.attributes["probable_hours"] == 1.0
    assert [o["status"] for o in tomorrow.attributes["outages"]] == ["outage", "probable"]
    assert state(hass, "sensor", "schedule").attributes["today"][-1]["end_time"] == "24:00"


async def test_all_day_power(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Queue 0.0 (no outages): power on, zero hours, empty calendar."""
    mock_schedule(aioclient_mock, "schedule_0_0.json")
    await setup(hass, config_entry)
    assert state(hass, "binary_sensor", "power").state == STATE_ON
    assert float(state(hass, "sensor", "outage_today").state) == 0.0
    assert state(hass, "calendar", "outages").state == STATE_OFF


async def test_empty_schedule_on_first_load(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An empty schedule sets up fine and reports unknown values."""
    mock_schedule(aioclient_mock, "schedule_9_9.json")
    await setup(hass, config_entry)
    assert state(hass, "binary_sensor", "power").state == STATE_UNKNOWN
    assert state(hass, "sensor", "schedule").state == "unknown"
    assert state(hass, "sensor", "outage_today").state == STATE_UNKNOWN
    assert state(hass, "sensor", "next_change").state == STATE_UNKNOWN


async def test_empty_answer_keeps_previous_schedule(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen: FrozenDateTimeFactory,
) -> None:
    """An empty response after a good one is treated as a hiccup."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_schedule(aioclient_mock, [])
    frozen.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert state(hass, "binary_sensor", "power").state == STATE_ON
    assert float(state(hass, "sensor", "outage_today").state) == 7.0


async def test_update_failure_marks_unavailable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    frozen: FrozenDateTimeFactory,
) -> None:
    """A failing refresh makes entities unavailable until the next success."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)

    aioclient_mock.clear_requests()
    mock_schedule(aioclient_mock, exc=TimeoutError())
    frozen.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state(hass, "binary_sensor", "power").state == STATE_UNAVAILABLE

    aioclient_mock.clear_requests()
    mock_schedule(aioclient_mock)
    frozen.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert state(hass, "binary_sensor", "power").state == STATE_ON


async def test_setup_retry_on_connection_error(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """If the first refresh fails, setup is retried later."""
    mock_schedule(aioclient_mock, status=500)
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The entry unloads cleanly."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_calendar_events(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """calendar.get_events returns the three outages of the day."""
    mock_schedule(aioclient_mock)
    await setup(hass, config_entry)
    entity_id = eid(hass, "calendar", "outages")
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": "2026-10-26T22:00:00+00:00",
            "end_date_time": "2026-10-27T22:00:00+00:00",
        },
        blocking=True,
        return_response=True,
    )
    events = response[entity_id]["events"]
    assert [(e["start"], e["end"]) for e in events] == [
        ("2026-10-27T08:00:00+02:00", "2026-10-27T10:00:00+02:00"),
        ("2026-10-27T13:00:00+02:00", "2026-10-27T16:00:00+02:00"),
        ("2026-10-27T19:00:00+02:00", "2026-10-27T21:00:00+02:00"),
    ]
    assert events[0]["summary"] == "Power outage"


async def test_two_addresses(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entry_data: dict[str, Any],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Several addresses (entries) work side by side."""
    mock_schedule(aioclient_mock)
    mock_schedule(aioclient_mock, "schedule_3_1.json", cherga=3, pidcherga=1)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Дача",
        unique_id="999|5|household",
        data={**entry_data, "address_id": "999", "house": "5", "cherga": 3, "pidcherga": 1},
    )
    await setup(hass, config_entry)
    await setup(hass, second)
    reg = er.async_get(hass)
    other = reg.async_get_entity_id("sensor", DOMAIN, "999|5|household_queue")
    assert other
    assert hass.states.get(other).state == "3.1"
    assert state(hass, "sensor", "queue").state == "1.2"


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Diagnostics redact the address and include the schedule."""
    mock_schedule(aioclient_mock)
    assert await async_setup_component(hass, "diagnostics", {})
    await setup(hass, config_entry)
    diag = await get_diagnostics_for_config_entry(hass, hass_client, config_entry)
    assert diag["entry"]["title"] == "**REDACTED**"
    assert diag["entry"]["data"]["house"] == "**REDACTED**"
    assert diag["entry"]["data"]["cherga"] == 1
    assert diag["schedule"]["slot_count"] == 48
    assert diag["schedule"]["days"] == ["2026-10-27"]
