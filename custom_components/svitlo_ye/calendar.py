"""Calendar of planned and probable outages."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SvitloYeConfigEntry
from .entity import SvitloYeEntity
from .schedule import Interval, ScheduleStatus

PARALLEL_UPDATES = 0

_SUMMARIES: dict[str, dict[ScheduleStatus, str]] = {
    "uk": {
        ScheduleStatus.OUTAGE: "Відключення світла",
        ScheduleStatus.PROBABLE: "Можливе відключення світла",
    },
    "en": {
        ScheduleStatus.OUTAGE: "Power outage",
        ScheduleStatus.PROBABLE: "Possible power outage",
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SvitloYeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([SvitloYeCalendar(entry.runtime_data.coordinator, "outages")])


class SvitloYeCalendar(SvitloYeEntity, CalendarEntity):
    """Outage events (sure and probable) of the published schedule."""

    def _event(self, interval: Interval) -> CalendarEvent:
        language = "uk" if self.hass.config.language.startswith("uk") else "en"
        queue = self.coordinator.data.queue
        description = (
            f"Черга {queue}. {self.coordinator.config_entry.title}"
            if language == "uk"
            else f"Queue {queue}. {self.coordinator.config_entry.title}"
        )
        return CalendarEvent(
            start=dt_util.as_local(interval.start),
            end=dt_util.as_local(interval.end),
            summary=_SUMMARIES[language][interval.status],
            description=description,
            uid=f"{self.unique_id}_{int(interval.start.timestamp())}",
        )

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming outage."""
        now = dt_util.utcnow()
        upcoming = (i for i in self.coordinator.data.outage_intervals() if i.end > now)
        interval = next(upcoming, None)
        return self._event(interval) if interval else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return outage events in a time range."""
        return [
            self._event(i)
            for i in self.coordinator.data.outage_intervals()
            if i.end > start_date and i.start < end_date
        ]
