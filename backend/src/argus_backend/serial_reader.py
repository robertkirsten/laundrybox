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
            path = self._resolve_port()
            if path is None:
                await self._sleep_or_stop(self._settings.serial_reconnect_s)
                continue

            device: serial.Serial | None = None
            connected = False
            try:
                device = await asyncio.to_thread(
                    serial.Serial,
                    str(path),
                    self._settings.serial_baud,
                    timeout=self._settings.serial_read_timeout_s,
                )
                connected = True
                logger.info("opened Teensy serial port %s", path)
                await self._on_connected()
                while not self._stop.is_set():
                    raw = await asyncio.to_thread(
                        device.read_until,
                        b"\n",
                        self._settings.max_serial_line_bytes + 1,
                    )
                    if not raw:
                        continue
                    logger.debug("Teensy serial: %s", raw.decode(errors="replace").rstrip())
                    if len(raw) > self._settings.max_serial_line_bytes:
                        logger.warning("discarding overlong serial line")
                        await asyncio.to_thread(device.reset_input_buffer)
                        continue
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

    def _resolve_port(self) -> Path | None:
        return next(
            (path for path in self._settings.candidate_serial_ports() if path.exists()),
            None,
        )

    async def _sleep_or_stop(self, seconds: float) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
