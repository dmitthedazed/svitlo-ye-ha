"""Button to refresh the schedule on demand."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SvitloYeConfigEntry
from .entity import SvitloYeEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SvitloYeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the refresh button."""
    async_add_entities([SvitloYeRefreshButton(entry.runtime_data.coordinator, "refresh")])


class SvitloYeRefreshButton(SvitloYeEntity, ButtonEntity):
    """Fetch the schedule right now."""

    _attr_device_class = ButtonDeviceClass.UPDATE

    async def async_press(self) -> None:
        """Refresh the coordinator."""
        await self.coordinator.async_request_refresh()
