"""Sensors for SvitloYE."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import SvitloYeConfigEntry, SvitloYeCoordinator
from .entity import SvitloYeEntity
from .schedule import STATUS_OPTIONS, ScheduleData, kyiv_today

PARALLEL_UPDATES = 0

SERVICE_GET_SCHEDULE = "get_schedule"
ATTR_DAYS = "days"

type ValueFn = Callable[[ScheduleData, datetime], StateType | datetime]
type AttrsFn = Callable[[ScheduleData, datetime], dict[str, Any]]


def _next_change(data: ScheduleData, now: datetime) -> datetime | None:
    change = data.next_power_change(now)
    return change[0] if change else None


def _next_change_attrs(data: ScheduleData, now: datetime) -> dict[str, Any]:
    change = data.next_power_change(now)
    return {"next_power_state": None if change is None else ("on" if change[1] else "off")}


def _minutes_to_change(data: ScheduleData, now: datetime) -> int | None:
    change = data.next_power_change(now)
    if change is None:
        return None
    return max(0, int((change[0] - now).total_seconds() // 60))


def _power_transition(power: bool) -> ValueFn:
    def value(data: ScheduleData, now: datetime) -> datetime | None:
        return data.next_power_transition(now, power)

    return value


def _day_hours(offset: int) -> ValueFn:
    def value(data: ScheduleData, now: datetime) -> float | None:
        stats = data.day_stats(kyiv_today(now) + timedelta(days=offset))
        return stats.outage_hours if stats else None

    return value


def _day_attrs(offset: int) -> AttrsFn:
    def attrs(data: ScheduleData, now: datetime) -> dict[str, Any]:
        day = kyiv_today(now) + timedelta(days=offset)
        stats = data.day_stats(day)
        intervals = data.day_intervals(day)
        return {
            "date": day.isoformat(),
            "published": stats is not None,
            "probable_hours": stats.probable_hours if stats else None,
            "available_hours": stats.available_hours if stats else None,
            "unknown_hours": stats.unknown_hours if stats else None,
            "outages": [i.as_dict() for i in intervals if i.status.value in ("outage", "probable")],
        }

    return attrs


def _schedule_attrs(data: ScheduleData, now: datetime) -> dict[str, Any]:
    today = kyiv_today(now)
    current = data.current(now)
    return {
        "queue": data.queue,
        "current": current.as_dict() if current else None,
        "today": [i.as_dict() for i in data.day_intervals(today)],
        "tomorrow": [i.as_dict() for i in data.day_intervals(today + timedelta(days=1))],
        "messages": [m.text for m in data.messages],
    }


@dataclass(frozen=True, kw_only=True)
class SvitloYeSensorDescription(SensorEntityDescription):
    """Describes a SvitloYE sensor."""

    value_fn: ValueFn
    attrs_fn: AttrsFn | None = None


SENSORS: tuple[SvitloYeSensorDescription, ...] = (
    SvitloYeSensorDescription(
        key="schedule",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        value_fn=lambda data, now: data.current_status(now).value,
        attrs_fn=_schedule_attrs,
    ),
    SvitloYeSensorDescription(
        key="next_change",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_next_change,
        attrs_fn=_next_change_attrs,
    ),
    SvitloYeSensorDescription(
        key="time_to_change",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_minutes_to_change,
        attrs_fn=_next_change_attrs,
    ),
    SvitloYeSensorDescription(
        key="next_power_off",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_power_transition(False),
    ),
    SvitloYeSensorDescription(
        key="next_power_on",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_power_transition(True),
    ),
    SvitloYeSensorDescription(
        key="queue",
        value_fn=lambda data, now: data.queue,
    ),
    SvitloYeSensorDescription(
        key="outage_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=_day_hours(0),
        attrs_fn=_day_attrs(0),
    ),
    SvitloYeSensorDescription(
        key="outage_tomorrow",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=_day_hours(1),
        attrs_fn=_day_attrs(1),
    ),
    SvitloYeSensorDescription(
        key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, now: data.last_updated,
        attrs_fn=lambda data, now: {
            "server_updated": data.server_updated.isoformat() if data.server_updated else None,
            "fetched_at": data.fetched_at.isoformat(),
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SvitloYeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(SvitloYeSensor(coordinator, description) for description in SENSORS)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_GET_SCHEDULE,
        {vol.Optional(ATTR_DAYS, default=2): vol.All(vol.Coerce(int), vol.Range(min=1, max=7))},
        "async_get_schedule",
        supports_response=SupportsResponse.ONLY,
    )


class SvitloYeSensor(SvitloYeEntity, SensorEntity):
    """A SvitloYE sensor."""

    entity_description: SvitloYeSensorDescription
    # Large, card-oriented attributes are not stored in the recorder database.
    _unrecorded_attributes = frozenset({"current", "today", "tomorrow", "messages", "outages"})

    def __init__(
        self, coordinator: SvitloYeCoordinator, description: SvitloYeSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data, dt_util.utcnow())

    async def async_get_schedule(self, days: int) -> ServiceResponse:
        """Return the schedule for the next ``days`` days (service with response)."""
        data = self.coordinator.data
        today = kyiv_today(dt_util.utcnow())
        return {
            "queue": data.queue,
            "server_updated": data.server_updated.isoformat() if data.server_updated else None,
            "days": {
                (today + timedelta(days=n)).isoformat(): [
                    i.as_dict() for i in data.day_intervals(today + timedelta(days=n))
                ]
                for n in range(days)
            },
        }
