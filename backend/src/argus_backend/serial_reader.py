from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

import serial
from pydantic import TypeAdapter, ValidationError
from serial import SerialException

from .config import Settings
from .schemas import TeensyMessage

logger = logging.getLogger(__name__)

MessageHandler = Callable[[TeensyMessage], Awaitable[None]]
StateHandler = Callable[[], Awaitable[None]]


class SerialReader:
    def __init__(
        self,
        settings: Settings,
        on_message: MessageHandler,
        on_connected: StateHandler,
        on_disconnected: StateHandler,
    ) -> None:
        self._settings = settings
        self._on_message = on_message
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._stop = asyncio.Event()
        self._adapter = TypeAdapter(TeensyMessage)

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            paths = self._resolve_ports()
            if not paths:
                await self._sleep_or_stop(self._settings.serial_reconnect_s)
                continue

            device: serial.Serial | None = None
            connected = False
            for path in paths:
                try:
                    device = await asyncio.to_thread(
                        serial.Serial,
                        str(path),
                        self._settings.serial_baud,
                        timeout=self._settings.serial_read_timeout_s,
                    )
                    break
                except (OSError, SerialException) as exc:
                    logger.debug("Failed to open %s: %s", path, exc)
                    
            if device is None:
                logger.warning("Could not open any Teensy serial port")
                await self._sleep_or_stop(self._settings.serial_reconnect_s)
                continue

            try:
                connected = True
                logger.info("opened Teensy serial port %s", getattr(device, "name", path))
                await self._on_connected()
                pending = bytearray()
                while not self._stop.is_set():
                    chunk = await asyncio.to_thread(
                        device.read_until,
                        b"\n",
                        self._settings.max_serial_line_bytes + 1 - len(pending),
                    )
                    if not chunk:
                        continue
                    pending.extend(chunk)
                    if len(pending) > self._settings.max_serial_line_bytes:
                        logger.warning("discarding overlong serial line")
                        pending.clear()
                        await asyncio.to_thread(device.reset_input_buffer)
                        continue
                    # pyserial returns partial data when its timeout expires,
                    # even when read_until() has not seen the delimiter yet.
                    # Preserve that fragment and finish the JSON frame on the
                    # next read instead of trying to validate both halves.
                    if not pending.endswith(b"\n"):
                        continue
                    raw = bytes(pending)
                    pending.clear()
                    logger.debug("Teensy serial: %s", raw.decode(errors="replace").rstrip())
                    try:
                        message = self._adapter.validate_json(raw)
                    except ValidationError as exc:
                        logger.warning("discarding invalid Teensy message: %s", exc)
                        continue
                    await self._on_message(message)
            except (OSError, SerialException) as exc:
                logger.warning("Teensy serial connection failed: %s", exc)
            finally:
                if device is not None and device.is_open:
                    await asyncio.to_thread(device.close)
                if connected:
                    await self._on_disconnected()
            await self._sleep_or_stop(self._settings.serial_reconnect_s)

    def _resolve_ports(self) -> list[Path]:
        return [
            path for path in self._settings.candidate_serial_ports() if path.exists()
        ]

    async def _sleep_or_stop(self, seconds: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
