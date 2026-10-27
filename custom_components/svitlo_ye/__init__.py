"""The SvitloYE integration: Zhytomyroblenergo power outage schedules."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SvitloYeApiClient
from .const import DOMAIN
from .coordinator import SvitloYeConfigEntry, SvitloYeCoordinator, SvitloYeRuntimeData

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
]


CARD_URL = f"/{DOMAIN}/svitlo-ye-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the Lovelace card and load it in the frontend."""
    if getattr(hass, "http", None) is None or "frontend" not in hass.config.components:
        return True
    from homeassistant.components.frontend import add_extra_js_url

    path = Path(__file__).parent / "www" / "svitlo-ye-card.js"
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(path), False)])
    add_extra_js_url(hass, CARD_URL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SvitloYeConfigEntry) -> bool:
    """Set up SvitloYE from a config entry."""
    client = SvitloYeApiClient(async_get_clientsession(hass))
    coordinator = SvitloYeCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start_ticker()

    entry.runtime_data = SvitloYeRuntimeData(client=client, coordinator=coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SvitloYeConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.coordinator.async_clear_issue()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: SvitloYeConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
