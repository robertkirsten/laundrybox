from __future__ import annotations

from argus_backend.events import SnapshotBroker
from argus_backend.repository import utc_now
from argus_backend.schemas import (
    DecisionReason,
    DisplaySnapshot,
    HealthSnapshot,
    Lifecycle,
    OperatorSnapshot,
    StationSnapshot,
)


def snapshot() -> DisplaySnapshot:
    return DisplaySnapshot(
        revision=0,
        updated_at=utc_now(),
        lifecycle=Lifecycle.WAITING,
        reason=DecisionReason.WAITING_FOR_GARMENT,
        scanned_count=0,
        station=StationSnapshot(code="ARGUS-01", name="ARGUS Check-Station"),
        operator=OperatorSnapshot(number="4471", display_name="M. Weber"),
        health=HealthSnapshot(
            backend_ok=True,
            database_ok=True,
            serial_connected=True,
            serial_fresh=True,
            rfid_ok=True,
            scale_ok=True,
        ),
    )


async def test_broker_revisions_and_resume_semantics() -> None:
    broker = SnapshotBroker(snapshot())
    assert (await broker.wait_after(-1, timeout_s=0.01)).revision == 0  # type: ignore[union-attr]
    assert await broker.wait_after(0, timeout_s=0.01) is None

    published = await broker.publish(snapshot())
    assert published.revision == 1
    resumed = await broker.wait_after(0, timeout_s=0.01)
    assert resumed is not None
    assert resumed.revision == 1
