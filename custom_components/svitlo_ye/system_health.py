"""System health for SvitloYE."""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import BASE_URL, DOMAIN


@callback
def async_register(hass: HomeAssistant, register: system_health.SystemHealthRegistration) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return system health info."""
    entries = hass.config_entries.async_entries(DOMAIN)
    return {
        "can_reach_server": system_health.async_check_can_reach_url(hass, BASE_URL),
        "configured_addresses": len(entries),
    }
