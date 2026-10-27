"""Event entity: schedule and power-state changes for automations."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SvitloYeConfigEntry, SvitloYeCoordinator
from .entity import SvitloYeEntity
from .schedule import ScheduleData, kyiv_today

PARALLEL_UPDATES = 0

EVENT_POWER_OFF = "power_off"
EVENT_POWER_ON = "power_on"
EVENT_SCHEDULE_CHANGED = "schedule_changed"
EVENT_TOMORROW_PUBLISHED = "tomorrow_published"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SvitloYeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity."""
    async_add_entities([SvitloYeScheduleEvent(entry.runtime_data.coordinator, "schedule_event")])


def _tomorrow_published(data: ScheduleData, now: datetime) -> bool:
    return data.day_stats(kyiv_today(now) + timedelta(days=1)) is not None


class SvitloYeScheduleEvent(SvitloYeEntity, EventEntity):
    """Fires when power goes off/on per schedule or the schedule itself changes."""

    def __init__(self, coordinator: SvitloYeCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._attr_event_types = [
            EVENT_POWER_OFF,
            EVENT_POWER_ON,
            EVENT_SCHEDULE_CHANGED,
            EVENT_TOMORROW_PUBLISHED,
        ]
        now = dt_util.utcnow()
        self._power = coordinator.data.current_status(now).has_power
        self._intervals = coordinator.data.intervals
        self._tomorrow = _tomorrow_published(coordinator.data, now)

    @callback
    def _handle_coordinator_update(self) -> None:
        data = self.coordinator.data
        now = dt_util.utcnow()

        power = data.current_status(now).has_power
        if power is not None and self._power is not None and power != self._power:
            self._trigger_event(EVENT_POWER_ON if power else EVENT_POWER_OFF, {"queue": data.queue})
        if power is not None:
            self._power = power

        tomorrow = _tomorrow_published(data, now)
        if tomorrow and not self._tomorrow:
            self._trigger_event(EVENT_TOMORROW_PUBLISHED, {"queue": data.queue})
        self._tomorrow = tomorrow

        if data.intervals != self._intervals:
            if self._intervals:
                self._trigger_event(EVENT_SCHEDULE_CHANGED, {"queue": data.queue})
            self._intervals = data.intervals

        super()._handle_coordinator_update()
