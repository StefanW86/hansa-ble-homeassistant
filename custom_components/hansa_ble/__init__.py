"""HANSA Connect BLE: control HANSA (Oras/Taelek) electronic fittings via Bluetooth."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import ATTR_DURATION, DOMAIN, MAX_FLUSH_SECONDS, SERVICE_FLUSH
from .coordinator import HansaConfigEntry, HansaCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

FLUSH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DURATION): vol.All(vol.Coerce(float), vol.Range(min=1, max=MAX_FLUSH_SECONDS)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def flush(call: ServiceCall) -> None:
        registry = dr.async_get(hass)
        coordinators: list[HansaCoordinator] = []
        for device_id in call.data[ATTR_DEVICE_ID]:
            device = registry.async_get(device_id)
            entry = next(
                (e for e in hass.config_entries.async_loaded_entries(DOMAIN) if device and e.entry_id == device.config_entry_id),
                None,
            )
            if entry is None:
                raise ServiceValidationError(f"{device_id} is not a loaded HANSA fitting")
            coordinators.append(entry.runtime_data)
        # Several fittings run in parallel (the proxy has 3 connection slots).
        await asyncio.gather(*(c.async_flush(call.data.get(ATTR_DURATION)) for c in coordinators))

    hass.services.async_register(DOMAIN, SERVICE_FLUSH, flush, schema=FLUSH_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HansaConfigEntry) -> bool:
    coordinator = HansaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: HansaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HansaConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
