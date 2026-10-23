"""BLE I/O for one HANSA fitting (connect, login fallback, commands, polling)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
import logging

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import protocol as p

_LOGGER = logging.getLogger(__name__)

VERIFY_READS = 4  # valve state is checked up to 4 x 0.5 s after OPEN
_sleep = asyncio.sleep  # patched in tests


class HansaError(Exception):
    """Communication failed."""


class HansaAuthError(HansaError):
    """Login rejected (wrong password)."""


@dataclass
class PollResult:
    state: p.DeviceState
    info: p.DeviceInfo
    param_a_min: bytes  # device limits for productParamA fields, same offsets
    param_a_max: bytes


class HansaClient:
    """Short-lived connections: connect per action, disconnect afterwards."""

    def __init__(
        self,
        address: str,
        name: str,
        password: str,
        type_code: int | None,
        ble_device: Callable[[], BLEDevice | None],
        now: Callable[[], datetime],
    ) -> None:
        self.address = address
        self.name = name
        self.password = password
        self.type_code = type_code
        self._ble_device = ble_device
        self._now = now
        self._lock = asyncio.Lock()
        self._info: p.DeviceInfo | None = None
        self._limits: tuple[bytes, bytes] | None = None

    # --- connection helpers -----------------------------------------------------------
    async def _connect(self) -> BleakClient:
        device = self._ble_device()
        if device is None:
            raise HansaError(f"{self.address} not in range of any connectable Bluetooth adapter/proxy")
        try:
            client = await establish_connection(
                BleakClientWithServiceCache, device, self.name, max_attempts=3,
                ble_device_callback=lambda: self._ble_device() or device,
            )
        except (BleakError, TimeoutError) as err:
            raise HansaError(f"connect failed: {err}") from err
        # The app writes the clock right after service discovery; do the same.
        try:
            await client.write_gatt_char(p.CHAR_TIME, p.time_payload(self.type_code, self._now()), response=True)
        except (BleakError, TimeoutError) as err:
            _LOGGER.debug("%s: time write failed: %s", self.address, err)
        return client

    @staticmethod
    async def _read(client: BleakClient, uuid: str, optional: bool = False) -> bytes:
        if optional and client.services.get_characteristic(uuid) is None:
            return b""
        return bytes(await client.read_gatt_char(uuid))

    async def _login(self, client: BleakClient) -> None:
        enc = await self._read(client, p.CHAR_PASSWORD)
        nonce = await self._read(client, p.CHAR_NONCE)
        await client.write_gatt_char(p.CHAR_PASSWORD, p.login_response(enc, nonce, self.password), response=True)
        if not p.login_ok(await self._read(client, p.CHAR_NONCE)):
            raise HansaAuthError("login rejected")

    async def _with_login_fallback(self, client: BleakClient, action: Callable[[], Awaitable[bool]]) -> None:
        """Run action without login (like the app); on rejection log in and retry once."""
        try:
            if await action():
                return
            _LOGGER.debug("%s: action not confirmed, retrying after login", self.address)
        except BleakError as err:
            _LOGGER.debug("%s: action rejected (%s), retrying after login", self.address, err)
        await self._login(client)
        if not await action():
            raise HansaError("device did not confirm the command")

    async def _command(self, client: BleakClient, cmd: int, expect_valve: bool | None = None) -> None:
        async def action() -> bool:
            await client.write_gatt_char(p.CHAR_COMMAND, bytes([cmd]), response=True)
            if expect_valve is None:
                return True
            for _ in range(VERIFY_READS):
                await _sleep(0.5)
                state_a = await self._read(client, p.CHAR_STATE_A)
                if len(state_a) > 3 and (state_a[3] == 1) == expect_valve:
                    return True
            return False

        await self._with_login_fallback(client, action)

    async def _run(self, func: Callable[[BleakClient], Awaitable]):
        async with self._lock:
            client = await self._connect()
            try:
                return await func(client)
            except (BleakError, TimeoutError) as err:
                raise HansaError(str(err) or type(err).__name__) from err
            finally:
                await client.disconnect()

    # --- public API -------------------------------------------------------------------
    async def poll(self) -> PollResult:
        async def read_all(client: BleakClient) -> PollResult:
            async def reads() -> list[bytes]:
                return [
                    await self._read(client, uuid, optional=True)
                    for uuid in (p.CHAR_STATE_A, p.CHAR_STATE_B, p.CHAR_COUNTERS_A, p.CHAR_COUNTERS_B,
                                 p.CHAR_COUNTERS_C, p.CHAR_PARAM_A, p.CHAR_PARAM_C)
                ]

            try:
                raw = await reads()
            except BleakError:
                await self._login(client)
                raw = await reads()
            if self._info is None:
                self._info = p.parse_info(
                    await self._read(client, p.CHAR_PRODUCT_INFO, optional=True),
                    await self._read(client, p.CHAR_PRODUCT_NAME, optional=True),
                )
            if self._limits is None:
                self._limits = (
                    await self._read(client, p.CHAR_PARAM_A_MIN, optional=True),
                    await self._read(client, p.CHAR_PARAM_A_MAX, optional=True),
                )
            return PollResult(p.parse_state(*raw), self._info, *self._limits)

        return await self._run(read_all)

    async def wink(self) -> None:
        await self._run(lambda c: self._command(c, p.CMD_WINK))

    async def start_cleaning_lock(self) -> None:
        await self._run(lambda c: self._command(c, p.CMD_CLOSE))

    async def reset_counters(self) -> None:
        await self._run(lambda c: self._command(c, p.CMD_COUNTER_RESET))

    async def normal(self) -> None:
        await self._run(lambda c: self._command(c, p.CMD_NORMAL, expect_valve=False))

    async def flush(self, duration: float) -> float:
        """Open, keep open for duration (capped at the device's maxOpenTime), then NORMAL.
        NORMAL is sent even if the wait is cancelled. Returns the effective duration."""
        async with self._lock:
            client = await self._connect()
            try:
                max_open = p.max_open_time(await self._read(client, p.CHAR_PARAM_A))
                if max_open:
                    duration = min(duration, max_open)
                try:
                    # Inside try: if OPEN went out but was not confirmed we still close.
                    await self._command(client, p.CMD_OPEN, expect_valve=True)
                    await _sleep(duration)
                finally:
                    if not client.is_connected:
                        client = await self._connect()
                    await self._command(client, p.CMD_NORMAL, expect_valve=False)
                return duration
            except (BleakError, TimeoutError) as err:
                raise HansaError(str(err) or type(err).__name__) from err
            finally:
                await client.disconnect()

    async def set_param(self, char: str, offset: int, value: int) -> None:
        """Change one 2 byte field of productParamA/C, keeping the rest of the block.
        Always logs in; uses the encrypted write when the device has encryption enabled."""

        async def write(client: BleakClient) -> None:
            await self._login(client)
            current = await self._read(client, char)
            new = plain = p.set_u16(current, offset, value, min_len=20 if char == p.CHAR_PARAM_A else 0)
            enc_flag = await self._read(client, p.CHAR_ENCRYPTION, optional=True)
            if enc_flag and enc_flag[0] & 1:
                enc = await self._read(client, p.CHAR_PASSWORD)
                nonce = await self._read(client, p.CHAR_NONCE)
                new = p.encrypt_write(new, enc, nonce)
            await client.write_gatt_char(char, new, response=True)
            check = await self._read(client, char)
            if check[offset : offset + 2] != plain[offset : offset + 2]:
                raise HansaError("device did not accept the new value")

        await self._run(write)

    async def check_login(self) -> None:
        await self._run(self._login)
