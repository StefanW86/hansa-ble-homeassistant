"""Buttons: flush (warm-up) and identify (wink)."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import HansaConfigEntry
from .entity import HansaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HansaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([FlushButton(c, "flush"), IdentifyButton(c, "identify")])


class FlushButton(HansaEntity, ButtonEntity):
    _attr_icon = "mdi:water-pump"

    async def async_press(self) -> None:
        await self.coordinator.async_flush()


class IdentifyButton(HansaEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_identify()
