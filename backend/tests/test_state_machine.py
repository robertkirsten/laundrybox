from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from argus_backend.config import Settings
from argus_backend.database import session_scope
from argus_backend.models import ScanCycle
from argus_backend.repository import Repository
from argus_backend.schemas import Decision, DecisionReason, Lifecycle, TeensyReport
from argus_backend.state_machine import CycleStateMachine

EPC = "E28011052000773410000001"


def report(
    weight_g: float | None, *, epc: str | None = None, stable: bool | None = None
) -> TeensyReport:
    tags = [] if epc is None else [{"epc": epc, "rssi": 91}]
    return TeensyReport(v=1, t=0, raw=None, weight_g=weight_g, tags=tags, stable=stable)


def test_restart_requires_empty_then_persists_pass_cycle(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    connected = machine.on_serial_connected()
    assert connected.lifecycle is Lifecycle.UNAVAILABLE
    assert connected.decision is None

    assert machine.on_report(report(0.0), now_monotonic=0.0) is None
    waiting = machine.on_report(report(0.0), now_monotonic=0.1)
    assert waiting is not None
    assert waiting.lifecycle is Lifecycle.WAITING

    started = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)
    acquiring = machine.on_report(report(239.8, epc=EPC), observed_at=started, now_monotonic=0.2)
    assert acquiring is not None
    assert acquiring.lifecycle is Lifecycle.ACQUIRING

    machine.on_report(
        report(240.0, epc=EPC),
        observed_at=started + timedelta(milliseconds=100),
        now_monotonic=0.3,
    )
    passed = machine.on_report(
        report(240.1, epc=EPC),
        observed_at=started + timedelta(milliseconds=200),
        now_monotonic=0.4,
    )
    assert passed is not None
    assert passed.lifecycle is Lifecycle.PASS
    assert passed.decision is Decision.PASS
    assert passed.reason is DecisionReason.WITHIN_THRESHOLD
    assert passed.garment is not None
    assert passed.garment.chute_number == 911
    assert passed.scanned_count == 1

    with session_scope(repository._factory) as session:  # type: ignore[attr-defined]
        cycle = session.scalar(select(ScanCycle))
        assert cycle is not None
        assert cycle.measured_weight_mg == 239_967
        assert cycle.reference_weight_mg == 240_000
        assert len(cycle.observations) == 1
        assert cycle.observations[0].read_count == 3

    assert machine.on_report(report(0.0), now_monotonic=0.5) is None
    ready_again = machine.on_report(report(0.0), now_monotonic=0.6)
    assert ready_again is not None
    assert ready_again.lifecycle is Lifecycle.WAITING
    assert ready_again.cycle_id is None


def test_missing_weight_can_never_produce_pass(settings: Settings, repository: Repository) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    snapshot = machine.on_report(report(None), now_monotonic=0.0)
    assert snapshot is not None
    assert snapshot.lifecycle is Lifecycle.UNAVAILABLE
    assert snapshot.decision is None
    assert snapshot.reason is DecisionReason.MISSING_WEIGHT
    assert not snapshot.health.scale_ok


def test_stale_serial_invalidates_active_measurement(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(240.0, epc=EPC), now_monotonic=0.2)

    stale = machine.tick(now_monotonic=0.2 + settings.serial_stale_after_s + 0.01)
    assert stale is not None
    assert stale.lifecycle is Lifecycle.UNAVAILABLE
    assert stale.reason is DecisionReason.SERIAL_STALE
    assert stale.decision is None


def test_acquisition_timeout_persists_check_when_tag_is_missing(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(240.0), now_monotonic=0.2)
    machine.on_report(report(240.1), now_monotonic=0.3)
    machine.on_report(report(239.9), now_monotonic=0.4)

    timed_out = machine.tick(now_monotonic=0.2 + settings.acquisition_timeout_s)
    assert timed_out is not None
    assert timed_out.lifecycle is Lifecycle.CHECK
    assert timed_out.decision is Decision.CHECK
    assert timed_out.reason is DecisionReason.MISSING_TAG
    assert timed_out.scanned_count == 0
