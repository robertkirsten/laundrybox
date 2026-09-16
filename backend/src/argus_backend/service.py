from __future__ import annotations

import asyncio
import logging

from pydantic import TypeAdapter

from .config import Settings
from .events import SnapshotBroker
from .repository import CycleNotFound, FeedbackConflict, Repository
from .schemas import (
    DisplaySnapshot,
    InspectionRequest,
    InspectionResponse,
    TeensyEvent,
    TeensyMessage,
    TeensyReport,
)
from .serial_reader import SerialReader
from .state_machine import CycleStateMachine

logger = logging.getLogger(__name__)


class StationService:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self.machine = CycleStateMachine(settings, repository)
        self.broker = SnapshotBroker(self.machine.initial_snapshot())
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._serial_reader: SerialReader | None = None
        self._debug_connected = False
        self._message_adapter = TypeAdapter(TeensyMessage)

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._monitor(), name="argus-monitor"))
        if self.settings.serial_enabled:
            self._serial_reader = SerialReader(
                self.settings,
                self.handle_message,
                self.serial_connected,
                self.serial_disconnected,
            )
            self._tasks.append(
                asyncio.create_task(self._serial_reader.run(), name="argus-serial-reader")
            )

    async def stop(self) -> None:
        if self._serial_reader is not None:
            self._serial_reader.stop()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def serial_connected(self) -> None:
        async with self._lock:
            await self.broker.publish(self.machine.on_serial_connected())

    async def serial_disconnected(self) -> None:
        async with self._lock:
            await self.broker.publish(self.machine.on_serial_disconnected())

    async def handle_message(self, message: TeensyMessage) -> None:
        async with self._lock:
            try:
                if isinstance(message, TeensyReport):
                    if message.auto_tare:
                        logger.info(
                            "scale auto-tared after garment removal; residual_g=%s",
                            message.tare_residual_g,
                        )
                    snapshot = self.machine.on_report(message)
                elif isinstance(message, TeensyEvent):
                    snapshot = self.machine.on_event(message)
                else:  # pragma: no cover - the TypeAdapter makes this unreachable
                    raise TypeError(f"unsupported Teensy message: {type(message)!r}")
            except Exception:
                logger.exception("message processing failed; station forced unavailable")
                snapshot = self.machine.on_database_error()
            if snapshot is not None:
                await self.broker.publish(snapshot)

    async def debug_ingest(self, payload: dict[str, object]) -> DisplaySnapshot:
        if not self.settings.enable_debug_ingest:
            raise PermissionError("debug ingest is disabled")
        if not self._debug_connected:
            self._debug_connected = True
            await self.serial_connected()
        message = self._message_adapter.validate_python(payload)
        await self.handle_message(message)
        return self.broker.current

    async def add_feedback(self, cycle_id: str, request: InspectionRequest) -> InspectionResponse:
        async with self._lock:
            try:
                response = self.repository.add_feedback(cycle_id, request)
            except (CycleNotFound, FeedbackConflict):
                raise
            except Exception:
                logger.exception("feedback write failed; station forced unavailable")
                await self.broker.publish(self.machine.on_database_error())
                raise
            snapshot = self.machine.mark_feedback_recorded(cycle_id, response.category)
            if snapshot is not None:
                await self.broker.publish(snapshot)
            return response

    async def _monitor(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.monitor_interval_s)
                async with self._lock:
                    try:
                        snapshot = self.machine.tick()
                    except Exception:
                        logger.exception("cycle monitor failed; station forced unavailable")
                        snapshot = self.machine.on_database_error()
                    if snapshot is not None:
                        await self.broker.publish(snapshot)
        except asyncio.CancelledError:
            raise
