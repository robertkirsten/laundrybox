from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from .config import Settings
from .schemas import Decision, DisplaySnapshot, InspectionCategory

logger = logging.getLogger(__name__)


Color = tuple[int, int, int]


class PixelStrip(Protocol):
    def fill(self, color: Color) -> None: ...

    def __setitem__(self, index: int, color: Color) -> None: ...

    def show(self) -> None: ...

    def deinit(self) -> None: ...


class StatusLed(Protocol):
    def show(self, snapshot: DisplaySnapshot) -> None: ...

    def close(self) -> None: ...


def show_solid_color(pixels: PixelStrip, color: Color) -> None:
    """Write a solid frame while preventing multi-channel RGB output."""
    if any(not isinstance(component, int) or not 0 <= component <= 255 for component in color):
        raise ValueError("RGB components must be integers between 0 and 255")
    if sum(component != 0 for component in color) > 1:
        raise ValueError("only one RGB color channel may be active at a time")
    pixels.fill(color)
    pixels.show()


class DisabledStatusLed:
    def show(self, snapshot: DisplaySnapshot) -> None:
        return None

    def close(self) -> None:
        return None


class NeoPixelStatusLed:
    """Drive a WS2813-compatible addressable strip through Raspberry Pi SPI."""

    def __init__(self, pixels: PixelStrip) -> None:
        self._pixels = pixels
        self._failed = False
        self._color: Color | None = None
        self._flash_task: asyncio.Task[None] | None = None
        self._set((0, 0, 0))

    def show(self, snapshot: DisplaySnapshot) -> None:
        if self._failed:
            return

        if snapshot.feedback_recorded:
            if self._flash_task is None or self._flash_task.done():
                flash_color = (0, 255, 0) if snapshot.feedback_category == InspectionCategory.NOTHING_FOUND else (255, 0, 0)
                self._flash_task = asyncio.create_task(self._flash_sequence(flash_color))
            return
        else:
            if self._flash_task and not self._flash_task.done():
                self._flash_task.cancel()
            self._flash_task = None

        color = (0, 0, 0)
        if snapshot.decision is Decision.CHECK:
            color = (255, 0, 0)
        elif snapshot.decision is Decision.PASS:
            color = (0, 255, 0)
        try:
            self._set(color)
        except Exception:
            self._failed = True
            logger.exception("NeoPixel status LED update failed; disabling LED output")

    async def _flash_sequence(self, flash_color: Color) -> None:
        try:
            for _ in range(3):
                self._set(flash_color)
                await asyncio.sleep(0.15)
                self._set((0, 0, 0))
                await asyncio.sleep(0.15)
            self._set(flash_color)
        except asyncio.CancelledError:
            pass
        except Exception:
            self._failed = True
            logger.exception("NeoPixel flash sequence failed")

    def close(self) -> None:
        if self._flash_task and not self._flash_task.done():
            self._flash_task.cancel()
        try:
            self._color = None
            self._set((0, 0, 0))
        except Exception:
            logger.exception("NeoPixel status LED could not be switched off")
        try:
            self._pixels.deinit()
        except Exception:
            logger.exception("NeoPixel status LED output could not be closed")

    def _set(self, color: Color) -> None:
        if color == self._color:
            return
        show_solid_color(self._pixels, color)
        self._color = color


def create_neopixel_strip(settings: Settings) -> PixelStrip:
    import board
    import neopixel_spi

    return neopixel_spi.NeoPixel_SPI(
        board.SPI(),
        settings.neopixel_count,
        brightness=settings.neopixel_brightness,
        pixel_order=neopixel_spi.GRB,
        auto_write=False,
        reset_time=0.0003,
    )


def create_status_led(settings: Settings) -> StatusLed:
    if not settings.neopixel_enabled:
        return DisabledStatusLed()
    pixels: PixelStrip | None = None
    try:
        pixels = create_neopixel_strip(settings)
        return NeoPixelStatusLed(pixels)
    except Exception:
        if pixels is not None:
            try:
                pixels.deinit()
            except Exception:
                logger.exception("partially initialized NeoPixel strip could not be closed")
        logger.exception("NeoPixel initialization failed; continuing without LED output")
        return DisabledStatusLed()
