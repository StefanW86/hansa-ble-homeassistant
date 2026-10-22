"""Switch: cleaning lock (CLOSE command; the device ends it after maxCloseTime)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_utc_time

from .coordinator import HansaConfigEntry
from .entity import HansaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HansaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([CleaningLockSwitch(entry.runtime_data, "cleaning_lock")])


class CleaningLockSwitch(HansaEntity, SwitchEntity):
    _attr_icon = "mdi:hand-wash"
    _unsub = None

    @property
    def is_on(self) -> bool:
        return self.coordinator.cleaning_lock_active

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_cleaning_lock(True)
        self._schedule_off()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_cleaning_lock(False)
        self.async_write_ha_state()

    def _schedule_off(self) -> None:
        if self._unsub:
            self._unsub()
        if until := self.coordinator.cleaning_lock_until:
            self._unsub = async_track_point_in_utc_time(self.hass, self._expired, until)

    @callback
    def _expired(self, _now) -> None:
        self._unsub = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
