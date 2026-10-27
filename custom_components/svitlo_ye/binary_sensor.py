"""Binary sensor: is there power according to the schedule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SvitloYeConfigEntry
from .entity import SvitloYeEntity
from .schedule import kyiv_today

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SvitloYeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            SvitloYePowerBinarySensor(coordinator, "power"),
            SvitloYeTomorrowBinarySensor(coordinator, "tomorrow_published"),
        ]
    )


class SvitloYePowerBinarySensor(SvitloYeEntity, BinarySensorEntity):
    """On when the schedule says there is power (probable outage counts as off)."""

    _attr_device_class = BinarySensorDeviceClass.POWER

    @property
    def is_on(self) -> bool | None:
        """Return True if power is expected now; None outside the schedule."""
        return self.coordinator.data.current_status(dt_util.utcnow()).has_power

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the current interval."""
        now = dt_util.utcnow()
        data = self.coordinator.data
        current = data.current(now)
        change = data.next_power_change(now)
        return {
            "status": data.current_status(now).value,
            "current_interval": current.as_dict() if current else None,
            "next_change": change[0].isoformat() if change else None,
            "queue": data.queue,
        }


class SvitloYeTomorrowBinarySensor(SvitloYeEntity, BinarySensorEntity):
    """On once the schedule for tomorrow is published."""

    @property
    def is_on(self) -> bool:
        """Return True if tomorrow's schedule is available."""
        tomorrow = kyiv_today(dt_util.utcnow()) + timedelta(days=1)
        return self.coordinator.data.day_stats(tomorrow) is not None
