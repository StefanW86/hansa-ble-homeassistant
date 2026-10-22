"""Base entity for HANSA Connect BLE."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HansaCoordinator


class HansaEntity(CoordinatorEntity[HansaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HansaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.address}_{key}"
        info = coordinator.data.info if coordinator.data else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.config_entry.title,
            manufacturer=MANUFACTURER,
            model=(info.product_name or None) if info else None,
            model_id=(info.product_number or None) if info else None,
            sw_version=str(info.firmware) if info and info.firmware is not None else None,
            serial_number=str(info.serial_number) if info and info.serial_number else None,
        )
