"""Numbers: flush duration (local setting) and cleaning-lock duration (device maxCloseTime)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import MAX_FLUSH_SECONDS
from .coordinator import HansaConfigEntry
from .entity import HansaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HansaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([FlushDuration(c, "flush_duration"), CleaningDuration(c, "cleaning_duration")])


class FlushDuration(HansaEntity, RestoreNumber):
    """How long "flush" keeps the water running. Stored in HA, capped by the device's maxOpenTime."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self.coordinator.flush_seconds = last.native_value

    @property
    def native_max_value(self) -> float:
        max_open = self.coordinator.data.state.max_open_time if self.coordinator.data else None
        return float(max_open or MAX_FLUSH_SECONDS)

    @property
    def native_value(self) -> float:
        return self.coordinator.flush_seconds

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.flush_seconds = value
        self.async_write_ha_state()


class CleaningDuration(HansaEntity, NumberEntity):
    """Device parameter maxCloseTime ("Cleaning mode time"); writing needs the device password."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:spray-bottle"

    @property
    def native_min_value(self) -> float:
        lo = self.coordinator.data.close_time_limits[0] if self.coordinator.data else None
        return float(lo or 1)

    @property
    def native_max_value(self) -> float:
        hi = self.coordinator.data.close_time_limits[1] if self.coordinator.data else None
        return float(hi or 3600)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.state.max_close_time if self.coordinator.data else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_cleaning_duration(int(value))
