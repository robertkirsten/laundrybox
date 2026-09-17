from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

from argus_backend.cli import _print_scan_table, led_test
from argus_backend.config import Settings
from argus_backend.repository import ScanLogEntry


def test_scan_table_contains_only_operator_fields() -> None:
    output = StringIO()
    _print_scan_table(
        [
            ScanLogEntry(
                cycle_id="cycle-1",
                completed_at=datetime(2026, 9, 16, tzinfo=UTC),
                epc="E280689400004031F0E235BE",
                garment_name="Jacke Schwarz",
                measured_weight_g=241.7,
                reference_weight_g=240.0,
            )
        ],
        output,
    )

    rendered = output.getvalue()
    assert "EPC" in rendered
    assert "GARMENT" in rendered
    assert "IST" in rendered
    assert "SOLL" in rendered
    assert "Jacke Schwarz" in rendered
    assert "241.7 g" in rendered
    assert "cycle-1" not in rendered
    assert "2026" not in rendered


class RecordingPixels:
    def __init__(self, count: int) -> None:
        self.buffer = [(0, 0, 0)] * count
        self.frames: list[tuple[tuple[int, int, int], ...]] = []
        self.deinitialized = False

    def fill(self, color: tuple[int, int, int]) -> None:
        self.buffer = [color] * len(self.buffer)

    def __setitem__(self, index: int, color: tuple[int, int, int]) -> None:
        self.buffer[index] = color

    def show(self) -> None:
        self.frames.append(tuple(self.buffer))

    def deinit(self) -> None:
        self.deinitialized = True


def test_led_test_never_lights_more_than_one_pixel(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        neopixel_enabled=True,
        neopixel_count=3,
        neopixel_brightness=0.2,
    )
    pixels = RecordingPixels(settings.neopixel_count)
    sleeps: list[float] = []
    monkeypatch.setattr("argus_backend.cli.create_neopixel_strip", lambda _settings: pixels)
    monkeypatch.setattr("argus_backend.cli.time.sleep", sleeps.append)

    led_test(settings, delay_s=0.01, cycles=1)

    assert len(sleeps) == settings.neopixel_count * 2
    assert all(sum(color != (0, 0, 0) for color in frame) <= 1 for frame in pixels.frames)
    assert pixels.frames[0] == ((0, 0, 0),) * settings.neopixel_count
    assert pixels.frames[-1] == ((0, 0, 0),) * settings.neopixel_count
    assert pixels.deinitialized
