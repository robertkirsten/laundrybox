from __future__ import annotations

import asyncio

from .schemas import DisplaySnapshot


class SnapshotBroker:
    def __init__(self, initial: DisplaySnapshot) -> None:
        self._snapshot = initial
        self._condition = asyncio.Condition()

    @property
    def current(self) -> DisplaySnapshot:
        return self._snapshot

    async def publish(self, snapshot: DisplaySnapshot) -> DisplaySnapshot:
        async with self._condition:
            revision = self._snapshot.revision + 1
            self._snapshot = snapshot.model_copy(update={"revision": revision})
            self._condition.notify_all()
            return self._snapshot

    async def wait_after(self, revision: int, timeout_s: float) -> DisplaySnapshot | None:
        async with self._condition:
            if self._snapshot.revision > revision:
                return self._snapshot
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._snapshot.revision > revision),
                    timeout=timeout_s,
                )
            except TimeoutError:
                return None
            return self._snapshot
