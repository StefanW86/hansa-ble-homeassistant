"""Binary sensors: valve open, sensor error."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HansaConfigEntry
from .entity import HansaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HansaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([ValveOpen(c, "valve"), SensorError(c, "sensor_error")])


class ValveOpen(HansaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_icon = "mdi:water"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.state.valve_open


class SensorError(HansaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.state.sensor_error
