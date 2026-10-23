"""Numbers: flush duration (local setting) and device parameters (cleaning lock, max open time, flow rate)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol as p
from .const import MAX_FLUSH_SECONDS
from .coordinator import HansaConfigEntry
from .entity import HansaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HansaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([
        FlushDuration(c, "flush_duration"),
        DeviceParam(c, "cleaning_duration", "max_close_time", p.CHAR_PARAM_A, p.PARAM_A_MAX_CLOSE_TIME, UnitOfTime.SECONDS,
                    "mdi:spray-bottle", 1, 3600, limit_from_device=True),
        # below 30 s the warm-up flush gets cut short
        DeviceParam(c, "max_open_time", "max_open_time", p.CHAR_PARAM_A, p.PARAM_A_MAX_OPEN_TIME, UnitOfTime.SECONDS,
                    "mdi:timer-lock-outline", 30, 3600, limit_from_device=True),
        # ponytail: 1-30 l/min is a guess, the device publishes no limits for productParamC
        DeviceParam(c, "flow_rate", "flow_rate", p.CHAR_PARAM_C, p.PARAM_C_FLOW_RATE, UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
                    "mdi:water-pump", 1, 30, decimals=1),
    ])


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


class DeviceParam(HansaEntity, NumberEntity):
    """A 2 byte field stored in the fitting (productParamA/C); writing needs the device password.
    raw = value * 10 ** decimals; limits come from the device where it publishes them."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, key, field, char, offset, unit, icon, lo, hi, decimals=0, limit_from_device=False):
        super().__init__(coordinator, key)
        self._field = field  # DeviceState attribute holding the parsed value
        self._char, self._offset, self._scale = char, offset, 10**decimals
        self._lo, self._hi, self._limit_from_device = lo, hi, limit_from_device
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_native_step = 1 / self._scale

    def _device_limits(self) -> tuple[int | None, int | None]:
        d = self.coordinator.data
        if not (self._limit_from_device and d):
            return None, None
        return p.u16_limits(d.param_a_min, d.param_a_max, self._offset)

    @property
    def native_min_value(self) -> float:
        return float(max(self._device_limits()[0] or self._lo, self._lo))

    @property
    def native_max_value(self) -> float:
        return float(self._device_limits()[1] or self._hi)

    @property
    def native_value(self) -> float | None:
        return getattr(self.coordinator.data.state, self._field) if self.coordinator.data else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_param(self._char, self._offset, round(value * self._scale))
