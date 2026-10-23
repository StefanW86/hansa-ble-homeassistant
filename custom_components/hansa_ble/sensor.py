"""Sensors: water consumption, counters, timings and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.components import bluetooth
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import PollResult
from .const import APP_CONTROL_MODES, BLUETOOTH_MODES
from .coordinator import HansaConfigEntry, HansaCoordinator
from .entity import HansaEntity


@dataclass(frozen=True, kw_only=True)
class HansaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PollResult, HansaCoordinator], float | int | str | None]


_COUNT = {"state_class": SensorStateClass.TOTAL_INCREASING}
_WATER = {
    "device_class": SensorDeviceClass.WATER,
    "state_class": SensorStateClass.TOTAL_INCREASING,
    "native_unit_of_measurement": UnitOfVolume.LITERS,
}
_DURATION_TOTAL = {
    "device_class": SensorDeviceClass.DURATION,
    "state_class": SensorStateClass.TOTAL_INCREASING,
    "native_unit_of_measurement": UnitOfTime.SECONDS,
}
_DIAG = {"entity_category": EntityCategory.DIAGNOSTIC}

SENSORS: tuple[HansaSensorDescription, ...] = (
    HansaSensorDescription(key="water_total", value_fn=lambda d, _: d.state.total_consumption, **_WATER),
    HansaSensorDescription(key="water_trip", value_fn=lambda d, _: d.state.trip_consumption, **_WATER),
    HansaSensorDescription(key="open_count_total", value_fn=lambda d, _: d.state.total_open_count, **_COUNT),
    HansaSensorDescription(key="open_count_trip", value_fn=lambda d, _: d.state.trip_open_count, **_COUNT),
    HansaSensorDescription(key="use_count_total", value_fn=lambda d, _: d.state.total_use_count, **_COUNT),
    HansaSensorDescription(key="use_count_trip", value_fn=lambda d, _: d.state.trip_use_count, **_COUNT),
    HansaSensorDescription(key="auto_flush_count", value_fn=lambda d, _: d.state.total_auto_flush_count, **_COUNT),
    HansaSensorDescription(key="open_time_total", value_fn=lambda d, _: d.state.total_open_time, **_DURATION_TOTAL),
    HansaSensorDescription(key="open_time_trip", value_fn=lambda d, _: d.state.trip_open_time, **_DURATION_TOTAL),
    HansaSensorDescription(
        key="since_last_use",
        value_fn=lambda d, _: d.state.seconds_since_use,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
    ),
    HansaSensorDescription(
        key="since_counter_reset",
        value_fn=lambda d, _: d.state.seconds_since_counter_reset,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.DAYS,
        **_DIAG,
    ),
    HansaSensorDescription(key="type_code", value_fn=lambda _, c: c.type_code, **_DIAG),
    HansaSensorDescription(
        key="bluetooth_mode",
        value_fn=lambda d, _: BLUETOOTH_MODES.get(d.state.bluetooth_mode),
        device_class=SensorDeviceClass.ENUM,
        options=list(BLUETOOTH_MODES.values()),
        **_DIAG,
    ),
    HansaSensorDescription(
        key="app_control",
        value_fn=lambda d, _: APP_CONTROL_MODES.get(d.state.app_control),
        device_class=SensorDeviceClass.ENUM,
        options=list(APP_CONTROL_MODES.values()),
        **_DIAG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: HansaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities([*(HansaSensor(c, d) for d in SENSORS), RssiSensor(c, "rssi")])


class HansaSensor(HansaEntity, SensorEntity):
    entity_description: HansaSensorDescription

    def __init__(self, coordinator: HansaCoordinator, description: HansaSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator)


class RssiSensor(HansaEntity, SensorEntity):
    """Signal strength of the last advertisement HA received (via the best adapter/proxy).
    Refreshed with every poll, also failed ones - so it stays useful when the fitting is unreachable."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _info(self):
        return bluetooth.async_last_service_info(self.hass, self.coordinator.address, connectable=False)

    @property
    def available(self) -> bool:
        return self._info() is not None

    @property
    def native_value(self) -> int | None:
        return info.rssi if (info := self._info()) else None
