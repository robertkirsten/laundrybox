from __future__ import annotations

import sys
from types import ModuleType

from argus_backend.schemas import Decision, Lifecycle
from argus_backend.status_led import NeoPixelStatusLed, create_status_led


class FakePixels:
    def __init__(self) -> None:
        self.color = (0, 0, 0)
        self.show_count = 0
        self.deinitialized = False

    def fill(self, color: tuple[int, int, int]) -> None:
        self.color = color

    def show(self) -> None:
        self.show_count += 1

    def deinit(self) -> None:
        self.deinitialized = True


def test_status_led_maps_pass_to_green_and_check_to_red(settings, repository) -> None:
    pixels = FakePixels()
    led = NeoPixelStatusLed(pixels)

    # Use the state machine's real snapshots so this test follows the public model.
    from argus_backend.state_machine import CycleStateMachine

    machine = CycleStateMachine(settings, repository)
    waiting = machine.on_serial_connected()
    led.show(waiting)
    assert pixels.color == (0, 0, 0)

    pass_snapshot = waiting.model_copy(
        update={"lifecycle": Lifecycle.PASS, "decision": Decision.PASS}
    )
    led.show(pass_snapshot)
    assert pixels.color == (0, 255, 0)

    check_snapshot = waiting.model_copy(
        update={"lifecycle": Lifecycle.CHECK, "decision": Decision.CHECK}
    )
    led.show(check_snapshot)
    assert pixels.color == (255, 0, 0)

    led.close()
    assert pixels.color == (0, 0, 0)
    assert pixels.deinitialized


def test_factory_configures_ws2813_compatible_spi_driver(settings, monkeypatch) -> None:
    pixels = FakePixels()
    captured: dict[str, object] = {}
    board = ModuleType("board")
    neopixel_spi = ModuleType("neopixel_spi")
    spi = object()
    board.SPI = lambda: spi  # type: ignore[attr-defined]
    neopixel_spi.GRB = "GRB"  # type: ignore[attr-defined]

    def make_pixels(spi_argument, count, **kwargs):
        captured.update(spi=spi_argument, count=count, **kwargs)
        return pixels

    neopixel_spi.NeoPixel_SPI = make_pixels  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "board", board)
    monkeypatch.setitem(sys.modules, "neopixel_spi", neopixel_spi)
    configured = settings.model_copy(
        update={"neopixel_enabled": True, "neopixel_count": 24, "neopixel_brightness": 0.15}
    )

    led = create_status_led(configured)

    assert isinstance(led, NeoPixelStatusLed)
    assert captured == {
        "spi": spi,
        "count": 24,
        "brightness": 0.15,
        "pixel_order": "GRB",
        "auto_write": False,
        "reset_time": 0.0003,
    }
