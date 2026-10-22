"""Polling coordinator + actions for one HANSA fitting."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import protocol as p
from .client import HansaAuthError, HansaClient, HansaError, PollResult
from .const import CONF_TYPE_CODE, DEFAULT_FLUSH_SECONDS, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

type HansaConfigEntry = ConfigEntry[HansaCoordinator]


class HansaCoordinator(DataUpdateCoordinator[PollResult]):
    """Owns the BLE client; entities read coordinator.data and call the action methods."""

    config_entry: HansaConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HansaConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=entry.title, update_interval=UPDATE_INTERVAL)
        self.address: str = entry.data[CONF_ADDRESS]
        type_code = entry.data.get(CONF_TYPE_CODE)
        if (info := bluetooth.async_last_service_info(hass, self.address, connectable=True)) is not None:
            type_code = p.parse_manufacturer_data(info.manufacturer_data).type_code or type_code
        self.type_code: int | None = type_code
        self.client = HansaClient(
            self.address,
            entry.title,
            entry.options.get(CONF_PASSWORD, entry.data[CONF_PASSWORD]),
            type_code,
            lambda: bluetooth.async_ble_device_from_address(hass, self.address, connectable=True),
            dt_util.now,
        )
        self.flush_seconds: float = DEFAULT_FLUSH_SECONDS
        self.cleaning_lock_until: datetime | None = None

    async def _async_update_data(self) -> PollResult:
        try:
            result = await self.client.poll()
        except HansaAuthError as err:
            raise UpdateFailed(f"Login failed, check the device password: {err}") from err
        except HansaError as err:
            raise UpdateFailed(str(err)) from err
        self._update_config_issue(result.state)
        return result

    def _update_config_issue(self, state: p.DeviceState) -> None:
        """Warn in Repairs when the fitting is configured to block remote control."""
        issue_id = f"config_{self.address}"
        if (state.bluetooth_mode or 0) != 0 or (state.app_control or 0) != 0:
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="remote_control_restricted",
                translation_placeholders={"name": self.config_entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # --- actions (entities and the flush service call these) --------------------------
    async def _action(self, coro) -> None:
        try:
            await coro
        except HansaAuthError as err:
            raise HomeAssistantError(f"{self.config_entry.title}: login rejected, check the password") from err
        except HansaError as err:
            raise HomeAssistantError(f"{self.config_entry.title}: {err}") from err
        finally:
            await self.async_request_refresh()

    async def async_flush(self, seconds: float | None = None) -> None:
        await self._action(self.client.flush(seconds or self.flush_seconds))

    async def async_identify(self) -> None:
        await self._action(self.client.wink())

    async def async_cleaning_lock(self, on: bool) -> None:
        if on:
            await self._action(self.client.start_cleaning_lock())
            seconds = self.data.state.max_close_time if self.data else None
            # ponytail: shown state is a local timer (device has no "cleaning" flag we know of)
            self.cleaning_lock_until = dt_util.utcnow() + timedelta(seconds=seconds or 60)
        else:
            self.cleaning_lock_until = None
            await self._action(self.client.normal())

    async def async_set_cleaning_duration(self, seconds: int) -> None:
        await self._action(self.client.set_max_close_time(seconds))

    @property
    def cleaning_lock_active(self) -> bool:
        return self.cleaning_lock_until is not None and dt_util.utcnow() < self.cleaning_lock_until
