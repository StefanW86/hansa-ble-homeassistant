"""In-memory HANSA fitting that speaks the GATT protocol (for tests only)."""

from __future__ import annotations

import hashlib

from bleak.exc import BleakError
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from custom_components.hansa_ble import protocol as p


class FakeFitting:
    def __init__(self, password: str = "Electra", require_login_for_commands: bool = False, encrypted: bool = False):
        self.password = password
        self.require_login = require_login_for_commands
        self.encrypted = encrypted
        self.temp_key = bytes(range(16))
        self.nonce = bytes(range(100, 116))
        self.logged_in = False
        self.valve = 0
        self.commands: list[int] = []
        self.time_writes: list[bytes] = []
        self.param_a = bytearray(20)
        self.param_a[12:14] = (60).to_bytes(2, "little")  # maxOpenTime
        self.param_a[14:16] = (600).to_bytes(2, "little")  # maxCloseTime
        self.connected = False
        self.stale_gatt_cache = False  # services look empty until clear_cache()
        self.cache_clears = 0
        self.ignore_open = False  # e.g. appControl = "opening disabled"
        self.param_c = bytearray(16)
        self.param_c[2:4] = (50).to_bytes(2, "little")  # flowRate 5.0 l/min

    # what the device exposes in CHAR_PASSWORD: temp key encrypted with the fixed key
    def _enc_password(self) -> bytes:
        return AESCCM(bytes([1] * 16), 8).encrypt(self.nonce[:13], self.temp_key, None)

    def read(self, uuid: str) -> bytes:
        if uuid == p.CHAR_PASSWORD:
            return self._enc_password()
        if uuid == p.CHAR_NONCE:
            return self.nonce[:-1] + (b"\xff" if self.logged_in else b"\x00")
        if uuid == p.CHAR_STATE_A:
            return bytes([0, 0, 0, self.valve]) + b"\0" * 12
        if uuid == p.CHAR_STATE_B:
            return b"\0" * 4 + (300).to_bytes(4, "little") + b"\0" * 12
        if uuid == p.CHAR_COUNTERS_A:
            return b"".join(v.to_bytes(4, "little") for v in (11, 10, 990, 1, 0))
        if uuid == p.CHAR_COUNTERS_B:
            return b"".join(v.to_bytes(4, "little") for v in (123, 4, 4, 300, 0))
        if uuid == p.CHAR_COUNTERS_C:
            return b"".join(v.to_bytes(4, "little") for v in (0, 7, 86400))
        if uuid == p.CHAR_PARAM_A:
            return bytes(self.param_a)
        if uuid == p.CHAR_PARAM_C:
            return bytes(self.param_c)
        if uuid == p.CHAR_PARAM_A_MIN:
            m = bytearray(20); m[14:16] = (10).to_bytes(2, "little"); return bytes(m)
        if uuid == p.CHAR_PARAM_A_MAX:
            m = bytearray(20); m[14:16] = (1800).to_bytes(2, "little"); return bytes(m)
        if uuid == p.CHAR_ENCRYPTION:
            return bytes([1 if self.encrypted else 0])
        if uuid == p.CHAR_PRODUCT_INFO:
            return b"8001030900" + b"0001" + bytes([42, 1, 10])
        if uuid == p.CHAR_PRODUCT_NAME:
            return (1935003891).to_bytes(4, "little") + b"HANSALIGNA".rjust(15, b"\0")
        raise BleakError(f"unknown characteristic {uuid}")

    def write(self, uuid: str, data: bytes) -> None:
        data = bytes(data)
        if uuid == p.CHAR_TIME:
            self.time_writes.append(data)
        elif uuid == p.CHAR_PASSWORD:
            md5 = hashlib.md5(self.password.encode()).digest()
            expected = AESCCM(self.temp_key, 8).encrypt(self.nonce[:13], md5, None)[:16]
            self.logged_in = data == expected
        elif uuid == p.CHAR_COMMAND:
            if self.require_login and not self.logged_in:
                raise BleakError("ATT error: insufficient authentication")
            self.commands.append(data[0])
            if data[0] == p.CMD_OPEN and self.ignore_open:
                return
            self.valve = {p.CMD_OPEN: 1, p.CMD_NORMAL: 0, p.CMD_CLOSE: 0}.get(data[0], self.valve)
        elif uuid in (p.CHAR_PARAM_A, p.CHAR_PARAM_C):
            if not self.logged_in:
                raise BleakError("ATT error: not logged in")
            if self.encrypted:
                data = AESCCM(self.temp_key, 8).decrypt(self.nonce[:13], data, None)
            (self.param_a if uuid == p.CHAR_PARAM_A else self.param_c)[:] = data
        else:
            raise BleakError(f"write to {uuid} not supported")


class FakeBleakClient:
    """Minimal BleakClient stand-in bound to a FakeFitting."""

    def __init__(self, fitting: FakeFitting):
        self.f = fitting
        self.f.connected = True
        self.f.logged_in = False  # login is per connection

    class _Services:
        def __init__(self, fitting: FakeFitting):
            self.f = fitting

        def get_characteristic(self, uuid):
            return None if self.f.stale_gatt_cache else object()

    @property
    def services(self):
        return self._Services(self.f)

    async def clear_cache(self) -> bool:
        self.f.stale_gatt_cache = False
        self.f.cache_clears += 1
        return True

    @property
    def is_connected(self) -> bool:
        return self.f.connected

    async def read_gatt_char(self, uuid):
        return self.f.read(uuid)

    async def write_gatt_char(self, uuid, data, response=True):
        self.f.write(uuid, data)

    async def disconnect(self):
        self.f.connected = False
