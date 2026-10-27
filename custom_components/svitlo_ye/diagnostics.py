"""Diagnostics for SvitloYE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS_ID, CONF_HOUSE, CONF_STREET_ID, CONF_STREET_NAME
from .coordinator import SvitloYeConfigEntry

TO_REDACT = {CONF_ADDRESS_ID, CONF_HOUSE, CONF_STREET_ID, CONF_STREET_NAME, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SvitloYeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "last_fetch_success": (
                coordinator.last_fetch_success.isoformat()
                if coordinator.last_fetch_success
                else None
            ),
        },
        "schedule": {
            "queue": data.queue,
            "server_updated": data.server_updated.isoformat() if data.server_updated else None,
            "fetched_at": data.fetched_at.isoformat(),
            "slot_count": len(data.slots),
            "days": sorted({s.day.isoformat() for s in data.slots}),
            "intervals": [i.as_dict() for i in data.intervals],
            "messages": [m.text for m in data.messages],
        },
    }
