"""Config flow: Bluetooth discovery, identify (wink), name + password."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_NAME, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from . import protocol as p
from .client import HansaAuthError, HansaClient, HansaError
from .const import CONF_TYPE_CODE, DOMAIN


class HansaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._info: BluetoothServiceInfoBleak | None = None
        self._wink_result = "–"
        self._candidates: dict[str, BluetoothServiceInfoBleak] = {}

    @property
    def _adv(self) -> p.Advertisement:
        return p.parse_manufacturer_data(self._info.manufacturer_data)

    def _client(self, password: str = p.DEFAULT_PASSWORD) -> HansaClient:
        address = self._info.address
        return HansaClient(
            address, self._info.name, password, self._adv.type_code,
            lambda: bluetooth.async_ble_device_from_address(self.hass, address, connectable=True),
            dt_util.now,
        )

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        if not p.is_hansa_name(discovery_info.name):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._info = discovery_info
        self.context["title_placeholders"] = {"name": self._title_hint()}
        return await self.async_step_confirm()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._info = self._candidates[user_input[CONF_ADDRESS]]
            await self.async_set_unique_id(self._info.address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_confirm()

        configured = self._async_current_ids(include_ignore=False)
        self._candidates = {
            i.address: i
            for i in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if p.is_hansa_name(i.name) and i.address not in configured
        }
        if not self._candidates:
            return self.async_abort(reason="no_devices_found")
        labels = {}
        for address, info in self._candidates.items():
            loc = p.parse_manufacturer_data(info.manufacturer_data).location
            labels[address] = f"{info.name}{f' – {loc}' if loc else ''} ({address}, {info.rssi} dBm)"
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(labels)})
        )

    def _title_hint(self) -> str:
        return self._adv.location or self._info.name or self._info.address

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="confirm",
            menu_options=["identify", "details"],
            description_placeholders={
                "name": self._info.name or "",
                "address": self._info.address,
                "location": self._adv.location or "–",
                "wink_result": self._wink_result,
            },
        )

    async def async_step_identify(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        try:
            await self._client().wink()
            self._wink_result = "✅"
        except HansaError as err:
            self._wink_result = f"❌ {err}"
        return await self.async_step_confirm()

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._client(user_input[CONF_PASSWORD]).check_login()
            except HansaAuthError:
                errors[CONF_PASSWORD] = "invalid_auth"
            except HansaError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_ADDRESS: self._info.address,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_TYPE_CODE: self._adv.type_code,
                    },
                )
        defaults = user_input or {CONF_NAME: self._title_hint(), CONF_PASSWORD: p.DEFAULT_PASSWORD}
        return self.async_show_form(
            step_id="details",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
                    vol.Required(CONF_PASSWORD, default=defaults[CONF_PASSWORD]): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return HansaOptionsFlow()


class HansaOptionsFlow(OptionsFlow):
    """Change the device password (the integration reloads afterwards)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_PASSWORD, self.config_entry.data[CONF_PASSWORD])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD, default=current): str}),
        )
