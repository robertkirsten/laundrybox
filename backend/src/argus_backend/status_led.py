from __future__ import annotations

import logging
from typing import Protocol

from .config import Settings
from .schemas import Decision, DisplaySnapshot

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
        self._set((0, 0, 0))

    def show(self, snapshot: DisplaySnapshot) -> None:
        if self._failed:
            return
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

    def close(self) -> None:
        try:
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
        self._pixels.fill(color)
        self._pixels.show()
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
