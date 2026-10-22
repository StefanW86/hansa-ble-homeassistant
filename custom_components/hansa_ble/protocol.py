"""HANSA / Oras (Taelek) BLE protocol: UUIDs, commands, crypto and payload parsing.

Pure functions only (no Home Assistant, no BLE I/O) so this module is unit-testable.
See HANSA_BLE_PROTOKOLL.md for where every value comes from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

# --- GATT characteristics -------------------------------------------------------------
CHAR_PRODUCT_INFO = "2be32db1-5f6b-4cbd-8813-8d6dfb164900"
CHAR_PRODUCT_NAME = "2be32db1-5f6b-4cbd-8823-8d6dfb164900"
CHAR_STATE_A = "2be32db1-5f6b-4cbd-8843-8d6dfb164900"
CHAR_STATE_B = "2be32db1-5f6b-4cbd-8853-8d6dfb164900"
CHAR_COUNTERS_A = "2be32db1-5f6b-4cbd-8863-8d6dfb164900"
CHAR_COUNTERS_B = "2be32db1-5f6b-4cbd-8873-8d6dfb164900"
CHAR_COUNTERS_C = "2be32db1-5f6b-4cbd-8883-8d6dfb164900"
CHAR_PARAM_A = "2be32db1-5f6b-5bd8-8138-d6dfb1649000"
CHAR_PARAM_C = "2be32db1-5f6b-5bd8-8338-d6dfb1649000"
CHAR_PARAM_A_MIN = "2be32db1-5f6b-5bd8-8438-d6dfb1649000"
CHAR_PARAM_A_MAX = "2be32db1-5f6b-5bd8-8738-d6dfb1649000"
CHAR_COMMAND = "2be32db1-5f6b-5bd8-8a38-d6dfb1649000"
CHAR_PASSWORD = "2be32db1-5f6b-5bd8-8b38-d6dfb1649000"
CHAR_TIME = "2be32db1-5f6b-5bd8-8c38-d6dfb1649000"
CHAR_NONCE = "2be32db1-5f6b-5bd8-8e8d-6dfb16490000"
CHAR_ENCRYPTION = "bfb53bad-6b00-402d-a1e5-be625ffaf10e"

# Only these characteristics need an encrypted write when encryption is enabled.
ENCRYPTED_WRITE_CHARS = {CHAR_PARAM_A, "2be32db1-5f6b-5bd8-8238-d6dfb1649000", CHAR_PARAM_C}

# --- Commands (1 byte to CHAR_COMMAND) --------------------------------------------------
CMD_WINK = 0x51
CMD_OPEN = 0x62
CMD_CLOSE = 0x73  # app button "Clean": cleaning lock for maxCloseTime seconds
CMD_NORMAL = 0x84  # app button "Close": back to sensor operation

# Advertised names the app accepts (substring match, ValveScanner.deviceBrands).
NAME_MARKERS = ("ORAS", "CYPRESS")

# productParamA offsets (identical for all basin/kitchen specs)
PARAM_A_MAX_OPEN_TIME = 12
PARAM_A_MAX_CLOSE_TIME = 14
# productParamC offsets
PARAM_C_FLOW_RATE = 2
PARAM_C_BLUETOOTH_MODE = 9
PARAM_C_APP_CONTROL = 13

DEFAULT_PASSWORD = "Electra"
_FIXED_KEY = bytes([0x01] * 16)
_TAG_LEN = 8

TYPE_NAMES = {
    0: "basin",
    1: "urinal",
    6: "basin_long",
    7: "spout",
    10: "basin_v2",
    11: "mira",
    13: "photocell",
    14: "kitchen",
    15: "shower",
}


def is_hansa_name(name: str | None) -> bool:
    """Same rule as the app: advertised name contains ORAS or CYPRESS (case-insensitive)."""
    return bool(name) and any(m in name.upper() for m in NAME_MARKERS)


@dataclass(frozen=True)
class Advertisement:
    type_code: int | None
    error_code: int | None
    location: str


def parse_manufacturer_data(manufacturer_data: dict[int, bytes]) -> Advertisement:
    """The app uses the last manufacturer entry, company id ignored."""
    if not manufacturer_data:
        return Advertisement(None, None, "")
    raw = list(manufacturer_data.values())[-1]
    if len(raw) < 3:
        return Advertisement(raw[0] if raw else None, None, "")
    location = bytes(b for b in raw[3:] if b).decode("utf-8", "ignore").strip()
    return Advertisement(raw[0], raw[2], location)


# --- Crypto ------------------------------------------------------------------------------
def _nonce(nonce: bytes) -> bytes:
    # SJCL CCM clamps the nonce to 15-L bytes; with <64 KiB payloads L=2 -> 13 bytes.
    n = bytes(nonce[:13])
    if len(n) < 7:
        raise ValueError("nonce too short")
    return n


def temp_key(encrypted_password: bytes, nonce: bytes) -> bytes:
    """Decrypt the device's temp key. CCM is CTR based: encrypting the ciphertext again
    decrypts it without tag check - exactly what the app does (it ignores the tag)."""
    ct = bytes(encrypted_password[:16]).ljust(16, b"\0")
    return AESCCM(_FIXED_KEY, _TAG_LEN).encrypt(_nonce(nonce), ct, None)[:16]


def login_response(encrypted_password: bytes, nonce: bytes, password: str) -> bytes:
    """16 bytes to write to CHAR_PASSWORD (JS encrypt_password)."""
    md5 = hashlib.md5(password.encode("utf-8")).digest()
    key = temp_key(encrypted_password, nonce)
    return AESCCM(key, _TAG_LEN).encrypt(_nonce(nonce), md5, None)[:16]


def login_ok(nonce_after_login: bytes) -> bool:
    return bool(nonce_after_login) and nonce_after_login[-1] == 0xFF


def encrypt_write(data: bytes, encrypted_password: bytes, nonce: bytes) -> bytes:
    """Encrypted parameter write (JS encrypt_data): ciphertext + 8 byte tag."""
    key = temp_key(encrypted_password, nonce)
    return AESCCM(key, _TAG_LEN).encrypt(_nonce(nonce), bytes(data), None)


# --- Time -----------------------------------------------------------------------------
def time_payload(type_code: int | None, now_local: datetime) -> bytes:
    """Value for CHAR_TIME, as TaelekService.writeTimeCharacteristic builds it."""
    if type_code is not None and type_code >= 10:
        # Wall-clock seconds since 2000-01-01 00:00 local time, 4 bytes LE.
        secs = int((now_local.replace(tzinfo=None) - datetime(2000, 1, 1)).total_seconds())
        return struct.pack("<I", secs)
    return bytes([now_local.hour, now_local.minute, now_local.second, now_local.isoweekday()])


# --- Parsing ---------------------------------------------------------------------------
def _u16(data: bytes, off: int) -> int | None:
    return int.from_bytes(data[off : off + 2], "little") if len(data) >= off + 2 else None


def _u32(data: bytes, off: int) -> int | None:
    return int.from_bytes(data[off : off + 4], "little") if len(data) >= off + 4 else None


def _u8(data: bytes, off: int) -> int | None:
    return data[off] if len(data) > off else None


def _str(data: bytes) -> str:
    return bytes(b for b in data if b).decode("utf-8", "ignore").strip()


def set_u16(data: bytes, off: int, value: int, min_len: int = 0) -> bytes:
    """Replace a 2 byte LE field, keeping every other byte (app: replaceDataSlice)."""
    buf = bytearray(data.ljust(max(min_len, off + 2), b"\0"))
    buf[off : off + 2] = int(value).to_bytes(2, "little")
    return bytes(buf)


@dataclass
class DeviceInfo:
    product_number: str
    hardware_number: str
    firmware: int | None
    serial_number: int | None
    product_name: str


def parse_info(product_info: bytes, product_name: bytes) -> DeviceInfo:
    return DeviceInfo(
        product_number=_str(product_info[0:10]),
        hardware_number=_str(product_info[10:14]),
        firmware=_u8(product_info, 14),
        serial_number=_u32(product_name, 0),
        product_name=_str(product_name[4:19]),
    )


@dataclass
class DeviceState:
    valve_open: bool | None
    sensor_error: bool | None
    seconds_since_use: int | None
    total_open_count: int | None
    total_use_count: int | None
    total_open_time: float | None  # s
    total_auto_flush_count: int | None
    total_consumption: int | None  # l
    trip_open_count: int | None
    trip_use_count: int | None
    trip_open_time: float | None  # s
    trip_consumption: int | None  # l
    seconds_since_counter_reset: int | None
    max_open_time: int | None  # s
    max_close_time: int | None  # s (cleaning lock duration)
    flow_rate: float | None  # l/min
    bluetooth_mode: int | None
    app_control: int | None


def _tenth(v: int | None) -> float | None:
    return None if v is None else round(v * 0.1, 1)


def parse_state(
    state_a: bytes, state_b: bytes, counters_a: bytes, counters_b: bytes, counters_c: bytes,
    param_a: bytes, param_c: bytes,
) -> DeviceState:
    valve = _u8(state_a, 3)
    err = _u8(state_a, 1)
    return DeviceState(
        valve_open=None if valve is None else valve == 1,
        sensor_error=None if err is None else err != 0,
        seconds_since_use=_u32(state_b, 4),
        total_open_count=_u32(counters_a, 0),
        total_use_count=_u32(counters_a, 4),
        total_open_time=_tenth(_u32(counters_a, 8)),
        total_auto_flush_count=_u32(counters_a, 12),
        total_consumption=_u32(counters_b, 0),
        trip_open_count=_u32(counters_b, 4),
        trip_use_count=_u32(counters_b, 8),
        trip_open_time=_tenth(_u32(counters_b, 12)),
        trip_consumption=_u32(counters_c, 4),
        seconds_since_counter_reset=_u32(counters_c, 8),
        max_open_time=_u16(param_a, PARAM_A_MAX_OPEN_TIME),
        max_close_time=_u16(param_a, PARAM_A_MAX_CLOSE_TIME),
        flow_rate=_tenth(_u16(param_c, PARAM_C_FLOW_RATE)),
        bluetooth_mode=_u8(param_c, PARAM_C_BLUETOOTH_MODE),
        app_control=_u8(param_c, PARAM_C_APP_CONTROL),
    )


def max_open_time(param_a: bytes) -> int | None:
    return _u16(param_a, PARAM_A_MAX_OPEN_TIME)


def max_close_time(param_a: bytes) -> int | None:
    return _u16(param_a, PARAM_A_MAX_CLOSE_TIME)


def max_close_time_limits(param_a_min: bytes, param_a_max: bytes) -> tuple[int | None, int | None]:
    return _u16(param_a_min, PARAM_A_MAX_CLOSE_TIME), _u16(param_a_max, PARAM_A_MAX_CLOSE_TIME)
