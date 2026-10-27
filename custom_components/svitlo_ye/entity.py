"""Base entity for SvitloYE."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONFIGURATION_URL, DOMAIN, MANUFACTURER
from .coordinator import SvitloYeCoordinator


class SvitloYeEntity(CoordinatorEntity[SvitloYeCoordinator]):
    """Common base: one service device per configured address."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SvitloYeCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        base_id = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=f"Черга {coordinator.cherga}.{coordinator.pidcherga}",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=CONFIGURATION_URL,
        )
