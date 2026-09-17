from __future__ import annotations

import pytest

from argus_backend.schemas import TeensyMessage, TeensyReport
from argus_backend.serial_reader import SerialReader


class FragmentedSerial:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)
        self.is_open = True

    def read_until(self, _delimiter: bytes, _size: int) -> bytes:
        try:
            return next(self.chunks)
        except StopIteration:
            raise OSError("test complete") from None

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False


@pytest.mark.asyncio
async def test_serial_reader_reassembles_a_line_split_by_timeout(settings, monkeypatch) -> None:
    settings = settings.model_copy(update={"serial_enabled": True})
    serial = FragmentedSerial(
        [
            b"{",
            b'"v":1,"t":1,"raw":0,"weight_g":0.0,"tags":[]}\r\n',
        ]
    )
    messages: list[TeensyMessage] = []

    async def on_message(message: TeensyMessage) -> None:
        messages.append(message)
        reader.stop()

    async def on_state_change() -> None:
        pass

    reader = SerialReader(settings, on_message, on_state_change, on_state_change)
    monkeypatch.setattr(reader, "_resolve_ports", lambda: [settings.serial_fallback_port])
    monkeypatch.setattr(
        "argus_backend.serial_reader.serial.Serial", lambda *_args, **_kwargs: serial
    )

    await reader.run()

    assert len(messages) == 1
    assert isinstance(messages[0], TeensyReport)
    assert messages[0].weight_g == 0.0
