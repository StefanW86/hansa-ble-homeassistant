"""Offline checks of the protocol module. Vectors were produced by the app's own
JavaScript (assets/raw/e.res -> encrypt_password / encrypt_data).

Run: python -m pytest tests/test_protocol.py   (needs: cryptography, pytest)
"""

from datetime import datetime
import importlib.util
from pathlib import Path
import sys

# Import protocol.py directly, without loading the HA integration package.
_spec = importlib.util.spec_from_file_location(
    "protocol", Path(__file__).parents[1] / "custom_components/hansa_ble/protocol.py"
)
p = importlib.util.module_from_spec(_spec)
sys.modules["protocol"] = p  # dataclasses need the module registered
_spec.loader.exec_module(p)

DEVICE_PW = bytes.fromhex("8f1c2a3b4c5d6e7f8091a2b3c4d5e6f7a1b2c3d4e5f60718")
NONCE = bytes.fromhex("00112233445566778899aabbccddeeff")


def test_login_response_matches_app_js():
    assert p.login_response(DEVICE_PW, NONCE, "Electra").hex() == "80b103da1c006472580d591cbbce228f"


def test_encrypted_write_matches_app_js():
    data = bytes(range(1, 21))
    assert p.encrypt_write(data, DEVICE_PW, NONCE).hex() == (
        "4fadf4fb7c2af6814e15029ebd78c228cc3f046a643ca6bb8eee8eee"
    )


def test_login_ok():
    assert p.login_ok(b"\x01\x02\xff")
    assert not p.login_ok(b"\x01\x02\x03")
    assert not p.login_ok(b"")


def test_time_payload():
    now = datetime(2026, 10, 22, 6, 30, 15)  # Thursday
    assert p.time_payload(0, now) == bytes([6, 30, 15, 4])
    secs = int((now - datetime(2000, 1, 1)).total_seconds())
    assert p.time_payload(10, now) == secs.to_bytes(4, "little")


def test_manufacturer_data():
    adv = p.parse_manufacturer_data({0x1234: b"\x0a\x64\x00\x00\x00Links\x00"})
    assert (adv.type_code, adv.error_code, adv.location) == (10, 0, "Links")
    assert p.parse_manufacturer_data({}).type_code is None


def test_name_filter():
    assert p.is_hansa_name("ORAS 123") and p.is_hansa_name("cypress")
    assert not p.is_hansa_name("Shelly") and not p.is_hansa_name(None)


def test_parse_state_and_param_patch():
    state_a = bytes([0, 0, 0, 1]) + b"\0" * 12
    state_b = b"\0" * 4 + (120).to_bytes(4, "little") + b"\0" * 12
    counters_a = b"".join(v.to_bytes(4, "little") for v in (7, 5, 123, 2, 0))
    counters_b = b"".join(v.to_bytes(4, "little") for v in (42, 3, 2, 50, 1))
    counters_c = b"".join(v.to_bytes(4, "little") for v in (0, 9, 3600))
    param_a = bytearray(20)
    param_a[12:14] = (60).to_bytes(2, "little")
    param_a[14:16] = (600).to_bytes(2, "little")
    param_c = bytearray(16)
    param_c[2:4] = (50).to_bytes(2, "little")
    param_c[13] = 1
    s = p.parse_state(state_a, state_b, counters_a, counters_b, counters_c, bytes(param_a), bytes(param_c))
    assert s.valve_open is True and s.sensor_error is False
    assert s.seconds_since_use == 120
    assert (s.total_open_count, s.total_use_count, s.total_open_time) == (7, 5, 12.3)
    assert (s.total_consumption, s.trip_consumption, s.seconds_since_counter_reset) == (42, 9, 3600)
    assert (s.max_open_time, s.max_close_time, s.flow_rate, s.app_control) == (60, 600, 5.0, 1)

    patched = p.set_u16(bytes(param_a), p.PARAM_A_MAX_CLOSE_TIME, 300)
    assert patched[14:16] == (300).to_bytes(2, "little")
    assert patched[:14] == bytes(param_a[:14]) and patched[16:] == bytes(param_a[16:])
