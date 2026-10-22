"""End-to-end tests against a real Home Assistant core with a simulated fitting."""

from __future__ import annotations

from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import ATTR_ENTITY_ID, CONF_ADDRESS, CONF_NAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, issue_registry as ir

from custom_components.hansa_ble import protocol as p
from custom_components.hansa_ble.const import CONF_TYPE_CODE, DOMAIN

ADDRESS = "AA:BB:CC:DD:EE:01"
pytestmark = pytest.mark.usefixtures("enable_bluetooth")


def _service_info(name: str = "ORAS 80010309") -> BluetoothServiceInfoBleak:
    mfr = {0x02E5: bytes([10, 100, 0]) + b"Links"}
    return BluetoothServiceInfoBleak(
        name=name, address=ADDRESS, rssi=-60, manufacturer_data=mfr, service_data={}, service_uuids=[],
        source="local", device=BLEDevice(ADDRESS, name, None), connectable=True, time=0, tx_power=None,
        advertisement=AdvertisementData(name, mfr, {}, [], None, -60, ()),
    )


@pytest.fixture(autouse=True)
def ble_device():
    with (
        patch("homeassistant.components.bluetooth.async_ble_device_from_address", return_value=BLEDevice(ADDRESS, "ORAS", None)),
        patch("homeassistant.components.bluetooth.async_last_service_info", return_value=_service_info()),
    ):
        yield


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, title="Waschtisch links",
        data={CONF_ADDRESS: ADDRESS, CONF_PASSWORD: "Electra", CONF_TYPE_CODE: 10},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_and_values(hass: HomeAssistant, fitting) -> None:
    entry = await _setup(hass)
    assert hass.states.get("sensor.waschtisch_links_water_total").state == "123"
    assert hass.states.get("sensor.waschtisch_links_openings_total").state == "11"
    assert hass.states.get("sensor.waschtisch_links_open_time_total").state == "99.0"
    assert hass.states.get("binary_sensor.waschtisch_links_valve").state == "off"
    assert hass.states.get("number.waschtisch_links_cleaning_lock_duration").state == "600"
    assert hass.states.get("number.waschtisch_links_flush_duration").state == "30"
    assert hass.states.get("sensor.waschtisch_links_bluetooth_mode").state == "always_on"
    # basin v2 (>=10) gets the 4-byte clock
    assert len(fitting.time_writes[-1]) == 4
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, ADDRESS), entry.entry_id)
    assert device.serial_number == "1935003891" and device.model == "HANSALIGNA"


async def test_flush_button_opens_then_normal(hass: HomeAssistant, fitting) -> None:
    await _setup(hass)
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.waschtisch_links_warm_up_flush"}, blocking=True)
    assert fitting.commands == [p.CMD_OPEN, p.CMD_NORMAL]
    assert fitting.valve == 0


async def test_flush_service_with_login_fallback(hass: HomeAssistant, fitting) -> None:
    fitting.require_login = True
    entry = await _setup(hass)
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, ADDRESS), entry.entry_id)
    await hass.services.async_call(DOMAIN, "flush", {"device_id": device.id, "duration": 5}, blocking=True)
    assert fitting.commands == [p.CMD_OPEN, p.CMD_NORMAL]


async def test_flush_wrong_password_raises(hass: HomeAssistant, fitting) -> None:
    fitting.require_login = True
    fitting.password = "geaendert"
    await _setup(hass)
    with pytest.raises(HomeAssistantError, match="login rejected"):
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.waschtisch_links_warm_up_flush"}, blocking=True)
    assert fitting.valve == 0


async def test_flush_unconfirmed_open_still_sends_normal(hass: HomeAssistant, fitting) -> None:
    fitting.ignore_open = True
    await _setup(hass)
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.waschtisch_links_warm_up_flush"}, blocking=True)
    # OPEN without login, OPEN after login, then the safety NORMAL
    assert fitting.commands == [p.CMD_OPEN, p.CMD_OPEN, p.CMD_NORMAL]


async def test_identify_and_cleaning_lock(hass: HomeAssistant, fitting) -> None:
    await _setup(hass)
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.waschtisch_links_identify"}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: "switch.waschtisch_links_cleaning_lock"}, blocking=True)
    assert hass.states.get("switch.waschtisch_links_cleaning_lock").state == "on"
    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: "switch.waschtisch_links_cleaning_lock"}, blocking=True)
    assert hass.states.get("switch.waschtisch_links_cleaning_lock").state == "off"
    assert fitting.commands == [p.CMD_WINK, p.CMD_CLOSE, p.CMD_NORMAL]


@pytest.mark.parametrize("encrypted", [False, True])
async def test_set_cleaning_duration(hass: HomeAssistant, fitting, encrypted: bool) -> None:
    fitting.encrypted = encrypted
    await _setup(hass)
    await hass.services.async_call(
        "number", "set_value", {ATTR_ENTITY_ID: "number.waschtisch_links_cleaning_lock_duration", "value": 300}, blocking=True
    )
    assert p.max_close_time(bytes(fitting.param_a)) == 300
    assert p.max_open_time(bytes(fitting.param_a)) == 60  # rest of the block untouched
    await hass.async_block_till_done()
    assert hass.states.get("number.waschtisch_links_cleaning_lock_duration").state == "300"


async def test_config_flow_bluetooth(hass: HomeAssistant, fitting) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_service_info()
    )
    assert result["type"] is FlowResultType.MENU and result["step_id"] == "confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "identify"})
    assert result["type"] is FlowResultType.MENU and result["description_placeholders"]["wink_result"] == "✅"
    assert fitting.commands == [p.CMD_WINK]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "details"})
    assert result["type"] is FlowResultType.FORM

    fitting.password = "Anders"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Waschtisch links", CONF_PASSWORD: "Electra"}
    )
    assert result["errors"] == {CONF_PASSWORD: "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Waschtisch links", CONF_PASSWORD: "Anders"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_PASSWORD: "Anders", CONF_TYPE_CODE: 10}


async def test_config_flow_ignores_other_devices(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_service_info("Shelly")
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "not_supported"


async def test_repair_issue_when_bluetooth_not_always_on(hass: HomeAssistant, fitting) -> None:
    fitting.bluetooth_mode = 1
    await _setup(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"config_{ADDRESS}") is not None
    assert hass.states.get("sensor.waschtisch_links_bluetooth_mode").state == "after_usage"
