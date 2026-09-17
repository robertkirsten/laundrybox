from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from argus_backend.config import Settings
from argus_backend.database import session_scope
from argus_backend.models import ScanCycle
from argus_backend.repository import Repository, RepositoryError
from argus_backend.schemas import (
    Decision,
    DecisionReason,
    InspectionCategory,
    InspectionRequest,
    Lifecycle,
    TeensyEvent,
    TeensyReport,
)
from argus_backend.state_machine import CycleStateMachine

EPC = "E28011052000773410000001"


def report(
    weight_g: float | None,
    *,
    epc: str | None = None,
    stable: bool | None = None,
    metal: bool | None = None,
) -> TeensyReport:
    tags = [] if epc is None else [{"epc": epc, "rssi": 91}]
    return TeensyReport(
        v=1, t=0, raw=None, weight_g=weight_g, tags=tags, stable=stable, metal=metal
    )


def _drive_metal_cycle(machine: CycleStateMachine):
    """Empty box, then a garment whose weight matches but trips the detector on
    one report. Metal latches for the whole cycle, so the second report need not
    repeat it. Returns the finalized snapshot."""
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(240.0, epc=EPC, stable=True, metal=True), now_monotonic=0.2)
    return machine.on_report(report(240.0, epc=EPC, stable=True), now_monotonic=0.3)


def test_metal_detection_forces_check_and_is_recorded(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    result = _drive_metal_cycle(machine)

    assert result is not None
    assert result.lifecycle is Lifecycle.CHECK
    assert result.decision is Decision.CHECK
    assert result.reason is DecisionReason.METAL_DETECTED
    assert result.metal_detected is True
    # Weight itself was within tolerance, so the indicator is the only trigger.
    assert result.measurement is not None
    assert result.measurement.difference_g == 0.0

    with session_scope(repository._factory) as session:  # type: ignore[attr-defined]
        cycle = session.scalar(select(ScanCycle))
        assert cycle is not None
        assert cycle.metal_detected is True
        assert cycle.reason == "metal_detected"


def test_metal_detection_can_be_disabled(settings: Settings, repository: Repository) -> None:
    disabled = settings.model_copy(update={"metal_check_enabled": False})
    machine = CycleStateMachine(disabled, repository)
    result = _drive_metal_cycle(machine)

    assert result is not None
    assert result.decision is Decision.PASS
    assert result.reason is DecisionReason.WITHIN_THRESHOLD
    assert result.metal_detected is False

    with session_scope(repository._factory) as session:  # type: ignore[attr-defined]
        cycle = session.scalar(select(ScanCycle))
        assert cycle is not None
        assert cycle.metal_detected is False


def test_restart_requires_empty_then_clears_pass_cycle_after_removal(
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

    scan = repository.recent_scan_log(limit=1)[0]
    assert scan.epc == EPC
    assert scan.garment_name == "Hose Blau"
    assert scan.measured_weight_g == 239.967
    assert scan.reference_weight_g == 240.0

    assert machine.on_report(report(0.0), now_monotonic=0.5) is None
    waiting = machine.on_report(report(0.0), now_monotonic=0.6)
    assert waiting is not None
    assert waiting.lifecycle is Lifecycle.WAITING
    assert waiting.cycle_id is None
    assert waiting.decision is None
    assert machine.result is None
    assert machine.active_cycle is None


def test_removed_check_result_stays_pending_until_feedback_is_recorded(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(250.0, epc=EPC, stable=True), now_monotonic=0.2)
    result = machine.on_report(report(250.0, epc=EPC, stable=True), now_monotonic=0.3)
    assert result is not None
    assert result.lifecycle is Lifecycle.CHECK
    assert result.cycle_id is not None

    assert machine.on_report(report(0.0), now_monotonic=0.4) is None

    completed = machine.mark_feedback_recorded(
        result.cycle_id, InspectionCategory.KEYS, now_monotonic=0.5
    )
    assert completed is not None
    # Feedback was recorded; the LED shows green confirmation while lifecycle
    # remains CHECK until the display timer expires.
    assert completed.lifecycle is Lifecycle.CHECK
    assert completed.feedback_recorded is True

    # Keep serial fresh with empty-box reports during the display period.
    machine.on_report(report(0.0), now_monotonic=1.0)
    machine.on_report(report(0.0), now_monotonic=2.0)
    machine.on_report(report(0.0), now_monotonic=3.0)

    # Before the display timer expires, tick should not transition.
    assert machine.tick(now_monotonic=3.0) is None

    # After the display timer expires, tick transitions to WAITING.
    # Serial is still fresh (last report at t=3.0, stale after 2.0s).
    waiting = machine.tick(now_monotonic=0.5 + settings.feedback_display_s + 0.1)
    assert waiting is not None
    assert waiting.lifecycle is Lifecycle.WAITING
    assert waiting.cycle_id is None


def test_new_garment_skips_unanswered_result_as_nothing_found(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(250.0, epc=EPC, stable=True), now_monotonic=0.2)
    result = machine.on_report(report(250.0, epc=EPC, stable=True), now_monotonic=0.3)
    assert result is not None
    assert result.cycle_id is not None
    assert result.lifecycle is Lifecycle.CHECK

    machine.on_report(report(0.0), now_monotonic=0.4)
    next_cycle = machine.on_report(report(620.0, epc="E28011052000773420000002"), now_monotonic=0.5)

    assert next_cycle is not None
    assert next_cycle.lifecycle is Lifecycle.ACQUIRING
    assert next_cycle.cycle_id != result.cycle_id
    assert repository.feedback_exists(result.cycle_id)
    recorded = repository.add_feedback(
        result.cycle_id,
        InspectionRequest(category=InspectionCategory.NOTHING_FOUND),
    )
    assert recorded.duplicate
    assert recorded.category is InspectionCategory.NOTHING_FOUND


def test_removed_check_result_times_out_as_nothing_found(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(250.0, epc=EPC, stable=True), now_monotonic=0.2)
    result = machine.on_report(report(250.0, epc=EPC, stable=True), now_monotonic=0.3)
    assert result is not None
    assert result.lifecycle is Lifecycle.CHECK
    assert result.cycle_id is not None

    machine.on_report(report(0.0), now_monotonic=0.4)
    assert (
        machine.tick(now_monotonic=0.4 + settings.inspection_timeout_s - 0.01) is None
    )
    assert not repository.feedback_exists(result.cycle_id)

    waiting = machine.tick(now_monotonic=0.4 + settings.inspection_timeout_s)
    assert waiting is not None
    assert waiting.lifecycle is Lifecycle.WAITING
    assert waiting.cycle_id is None
    recorded = repository.add_feedback(
        result.cycle_id,
        InspectionRequest(category=InspectionCategory.NOTHING_FOUND),
    )
    assert recorded.duplicate
    assert recorded.category is InspectionCategory.NOTHING_FOUND


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


def test_empty_confirmation_requires_a_stable_near_zero_band(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()

    assert machine.on_report(report(-50.0), now_monotonic=0.0).lifecycle is Lifecycle.UNAVAILABLE  # type: ignore[union-attr]
    assert machine.on_report(report(0.0), now_monotonic=0.1) is None
    assert machine.on_report(report(5.0), now_monotonic=0.2) is None
    assert machine.on_report(report(0.0), now_monotonic=0.3) is None

    waiting = machine.on_report(report(0.2), now_monotonic=0.4)
    assert waiting is not None
    assert waiting.lifecycle is Lifecycle.WAITING


def test_rfid_configuration_fault_is_latched_until_boot(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    fault = machine.on_event(TeensyEvent(v=1, event="rfid_config_error", step="eu_region"))
    assert fault.reason is DecisionReason.RFID_CONFIGURATION_ERROR

    blocked = machine.on_report(report(240.0, epc=EPC, stable=True), now_monotonic=0.1)
    assert blocked is not None
    assert blocked.lifecycle is Lifecycle.UNAVAILABLE
    assert blocked.decision is None
    assert not blocked.health.rfid_ok

    machine.on_event(TeensyEvent(v=1, event="boot"), now_monotonic=0.2)
    machine.on_report(report(0.0), now_monotonic=0.3)
    waiting = machine.on_report(report(0.0), now_monotonic=0.4)
    assert waiting is not None
    assert waiting.lifecycle is Lifecycle.WAITING


def test_database_failure_forces_unavailable_and_never_passes(
    settings: Settings, repository: Repository, monkeypatch
) -> None:
    machine = CycleStateMachine(settings, repository)
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(240.0, epc=EPC, stable=True), now_monotonic=0.2)

    def fail_lookup(_epc: str):
        raise RepositoryError("simulated database failure")

    monkeypatch.setattr(repository, "garment_by_epc", fail_lookup)
    failed = machine.on_report(report(240.0, epc=EPC, stable=True), now_monotonic=0.3)
    assert failed is not None
    assert failed.lifecycle is Lifecycle.UNAVAILABLE
    assert failed.decision is None
    assert failed.reason is DecisionReason.DATABASE_ERROR
    assert not failed.health.database_ok
    assert failed.scanned_count == 0

    still_failed = machine.on_report(report(0.0), now_monotonic=0.4)
    assert still_failed is not None
    assert still_failed.reason is DecisionReason.DATABASE_ERROR
    assert still_failed.decision is None


UNKNOWN_EPC = "AABB00112233445566778899"


def _drive_to_new_garment_prompt(
    machine: CycleStateMachine, *, weight_g: float = 240.0, epc: str = UNKNOWN_EPC
):
    """Empty box, then a single stable but unknown tag. Returns the prompt
    snapshot (lifecycle NEW_GARMENT)."""
    machine.on_serial_connected()
    machine.on_report(report(0.0), now_monotonic=0.0)
    machine.on_report(report(0.0), now_monotonic=0.1)
    machine.on_report(report(weight_g, epc=epc, stable=True), now_monotonic=0.2)
    return machine.on_report(report(weight_g, epc=epc, stable=True), now_monotonic=0.3)


def test_unknown_tag_opens_new_garment_prompt_without_persisting(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    snap = _drive_to_new_garment_prompt(machine)

    assert snap is not None
    assert snap.lifecycle is Lifecycle.NEW_GARMENT
    assert snap.reason is DecisionReason.NEW_GARMENT_DETECTED
    assert snap.decision is None
    assert snap.pending_epc == UNKNOWN_EPC
    assert snap.measurement is not None
    assert snap.measurement.measured_g == 240.0
    # Fail-closed: nothing is recorded until the operator answers.
    with session_scope(repository._factory) as session:  # type: ignore[attr-defined]
        assert session.scalar(select(ScanCycle)) is None


def test_register_new_garment_captures_reference_and_passes(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    _drive_to_new_garment_prompt(machine)
    assert machine.active_cycle is not None
    cycle_id = machine.active_cycle.cycle_id

    snap = machine.register_new_garment(cycle_id, product_name="Kittel", wearer_name="A. Schmidt")

    assert snap is not None
    assert snap.lifecycle is Lifecycle.PASS
    assert snap.decision is Decision.PASS
    assert snap.reason is DecisionReason.WITHIN_THRESHOLD
    assert snap.pending_epc is None
    assert snap.garment is not None
    assert snap.garment.product_name == "Kittel"
    assert snap.garment.wearer_name == "A. Schmidt"
    assert snap.measurement is not None
    assert snap.measurement.reference_g == 240.0
    assert snap.measurement.difference_g == 0.0
    assert machine.scanned_count == 1

    lookup = repository.garment_by_epc(UNKNOWN_EPC)
    assert lookup is not None
    assert lookup.reference_weight_mg == 240_000
    with session_scope(repository._factory) as session:  # type: ignore[attr-defined]
        cycle = session.scalar(select(ScanCycle))
        assert cycle is not None
        assert cycle.garment_id is not None
        assert cycle.decision == "PASS"


def test_register_blank_names_use_placeholders(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    _drive_to_new_garment_prompt(machine)
    assert machine.active_cycle is not None
    cycle_id = machine.active_cycle.cycle_id

    snap = machine.register_new_garment(cycle_id, product_name=None, wearer_name=None)

    assert snap is not None
    assert snap.garment is not None
    assert snap.garment.product_name == "Neues Kleidungsstück"
    assert snap.garment.wearer_name == "Nicht zugeordnet"
    assert snap.garment.customer_number == "AUTO"


def test_dismiss_new_garment_records_check(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    _drive_to_new_garment_prompt(machine)
    assert machine.active_cycle is not None
    cycle_id = machine.active_cycle.cycle_id

    snap = machine.dismiss_new_garment(cycle_id)

    assert snap is not None
    assert snap.lifecycle is Lifecycle.CHECK
    assert snap.decision is Decision.CHECK
    assert snap.reason is DecisionReason.UNKNOWN_TAG
    assert machine.scanned_count == 0
    assert repository.garment_by_epc(UNKNOWN_EPC) is None
    with session_scope(repository._factory) as session:  # type: ignore[attr-defined]
        cycle = session.scalar(select(ScanCycle))
        assert cycle is not None
        assert cycle.garment_id is None
        assert cycle.reason == "unknown_tag"


def test_new_garment_prompt_times_out_to_check(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    _drive_to_new_garment_prompt(machine)  # prompt entered at now_monotonic=0.3
    # Garment stays on the plate (serial link fresh) but the operator never answers.
    assert machine.on_report(report(240.0, epc=UNKNOWN_EPC, stable=True), now_monotonic=2.2) is None
    assert machine.lifecycle is Lifecycle.NEW_GARMENT

    snap = machine.tick(now_monotonic=0.3 + settings.inspection_timeout_s + 0.1)

    assert snap is not None
    assert snap.lifecycle is Lifecycle.CHECK
    assert snap.reason is DecisionReason.UNKNOWN_TAG
    assert repository.garment_by_epc(UNKNOWN_EPC) is None


def test_new_garment_prompt_removed_records_check(
    settings: Settings, repository: Repository
) -> None:
    machine = CycleStateMachine(settings, repository)
    _drive_to_new_garment_prompt(machine)

    snap = machine.on_report(report(0.0), now_monotonic=0.4)

    assert snap is not None
    assert snap.lifecycle is Lifecycle.CHECK
    assert snap.reason is DecisionReason.UNKNOWN_TAG
    assert machine.scanned_count == 0
