from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from uuid import uuid4

from .config import Settings
from .decision import DecisionResult, evaluate_cycle
from .repository import (
    CycleWrite,
    GarmentAlreadyExists,
    GarmentLookup,
    Repository,
    RuntimeContext,
    TagStat,
    utc_now,
)
from .schemas import (
    Decision,
    DecisionReason,
    DisplaySnapshot,
    HealthSnapshot,
    InspectionCategory,
    InspectionRequest,
    Lifecycle,
    MeasurementSnapshot,
    TeensyEvent,
    TeensyReport,
)

logger = logging.getLogger(__name__)


@dataclass
class MutableTagStat:
    epc: str
    first_seen_at: datetime
    last_seen_at: datetime
    read_count: int = 0
    max_rssi: int = 0

    def observe(self, observed_at: datetime, rssi: int) -> None:
        self.last_seen_at = observed_at
        self.read_count += 1
        self.max_rssi = max(self.max_rssi, rssi)

    def freeze(self) -> TagStat:
        return TagStat(
            epc=self.epc,
            first_seen_at=self.first_seen_at,
            last_seen_at=self.last_seen_at,
            read_count=self.read_count,
            max_rssi=self.max_rssi,
        )


@dataclass
class ActiveCycle:
    cycle_id: str
    started_at: datetime
    started_monotonic: float
    weights_g: deque[float]
    tags: dict[str, MutableTagStat] = field(default_factory=dict)
    calibration_version: str | None = None
    metal_detected: bool = False


class CycleStateMachine:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository
        self.context: RuntimeContext = repository.runtime_context()
        self.scanned_count = repository.completed_known_cycle_count()
        self.serial_connected = False
        self.last_report_monotonic: float | None = None
        self.rfid_fault_latched = False
        self.rfid_ok = False
        self.scale_ok = False
        self.database_ok = True
        self.needs_empty = True
        self.empty_weights: deque[float] = deque(maxlen=settings.removal_confirm_samples)
        self.active_cycle: ActiveCycle | None = None
        self.result: DecisionResult | None = None
        self.result_garment: GarmentLookup | None = None
        self.result_removed = False
        self.result_removed_monotonic: float | None = None
        self.feedback_category: InspectionCategory | None = None
        self.feedback_recorded_monotonic: float | None = None
        # Set while the lifecycle is NEW_GARMENT: an unknown but otherwise valid
        # garment is held (not yet persisted) awaiting the operator's decision to
        # register it or dismiss the prompt.
        self.pending_epc: str | None = None
        self.pending_measured_weight_g: float | None = None
        self.pending_since_monotonic: float | None = None
        self.lifecycle = Lifecycle.UNAVAILABLE
        self.reason = DecisionReason.SERIAL_DISCONNECTED

    def initial_snapshot(self) -> DisplaySnapshot:
        return self._snapshot()

    def on_serial_connected(self) -> DisplaySnapshot:
        self.serial_connected = True
        self.last_report_monotonic = None
        self._reset_cycle(require_empty=True)
        self.lifecycle = Lifecycle.UNAVAILABLE
        self.reason = DecisionReason.WAITING_FOR_EMPTY_BOX
        return self._snapshot()

    def on_serial_disconnected(self) -> DisplaySnapshot:
        self.serial_connected = False
        self.last_report_monotonic = None
        self.rfid_ok = False
        self.scale_ok = False
        self._reset_cycle(require_empty=True)
        self.lifecycle = Lifecycle.UNAVAILABLE
        self.reason = DecisionReason.SERIAL_DISCONNECTED
        return self._snapshot()

    def on_event(self, event: TeensyEvent, now_monotonic: float | None = None) -> DisplaySnapshot:
        self.last_report_monotonic = (
            now_monotonic if now_monotonic is not None else time.monotonic()
        )
        self._reset_cycle(require_empty=True)
        self.lifecycle = Lifecycle.UNAVAILABLE
        if event.event == "boot":
            self.reason = DecisionReason.TEENSY_RESTARTED
            self.rfid_fault_latched = False
            self.rfid_ok = False
            self.scale_ok = False
        else:
            self.reason = DecisionReason.RFID_CONFIGURATION_ERROR
            self.rfid_fault_latched = True
            self.rfid_ok = False
        return self._snapshot()

    def on_report(
        self,
        report: TeensyReport,
        *,
        observed_at: datetime | None = None,
        now_monotonic: float | None = None,
    ) -> DisplaySnapshot | None:
        observed_at = observed_at or utc_now()
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        self.serial_connected = True
        self.last_report_monotonic = now_monotonic

        if report.weight_g is None or not isfinite(report.weight_g):
            self.scale_ok = False
            self._reset_cycle(require_empty=True)
            self.lifecycle = Lifecycle.UNAVAILABLE
            self.reason = DecisionReason.MISSING_WEIGHT
            return self._snapshot()

        self.scale_ok = True
        if self.rfid_fault_latched:
            self.rfid_ok = False
            self._reset_cycle(require_empty=True)
            self.lifecycle = Lifecycle.UNAVAILABLE
            self.reason = DecisionReason.RFID_CONFIGURATION_ERROR
            return self._snapshot()
        self.rfid_ok = True
        if not self.database_ok:
            self._reset_cycle(require_empty=True)
            self.lifecycle = Lifecycle.UNAVAILABLE
            self.reason = DecisionReason.DATABASE_ERROR
            return self._snapshot()

        weight_g = report.weight_g

        if self.needs_empty:
            if self._observe_empty(weight_g, report.stable):
                self.needs_empty = False
                self.empty_weights.clear()
                self.lifecycle = Lifecycle.WAITING
                self.reason = DecisionReason.WAITING_FOR_GARMENT
                return self._snapshot()
            if abs(weight_g) <= self.settings.empty_weight_max_g:
                return None
            self.lifecycle = Lifecycle.UNAVAILABLE
            self.reason = DecisionReason.REMOVE_GARMENT_AFTER_RESTART
            return self._snapshot()

        if self.pending_epc is not None:
            # A new-garment prompt is on screen. Removing the garment without an
            # answer records it as a CHECK (fail-closed); otherwise keep waiting
            # for the operator, and let tick() enforce the registration timeout.
            if abs(weight_g) <= self.settings.empty_weight_max_g:
                return self._resolve_pending_as_check(completed_at=observed_at)
            return None

        if self.result is not None:
            # A PASS needs no operator inspection. Once the garment has been
            # removed and the empty box is confirmed, immediately return the
            # display to the ready state.
            if self.result.decision is Decision.PASS:
                if self._observe_empty(weight_g, report.stable):
                    self._reset_cycle(require_empty=False)
                    self.lifecycle = Lifecycle.WAITING
                    self.reason = DecisionReason.WAITING_FOR_GARMENT
                    return self._snapshot()
                return None

            if self.feedback_category is not None:
                if (
                    self._observe_empty(weight_g, report.stable)
                    and self.feedback_recorded_monotonic is not None
                    and now_monotonic - self.feedback_recorded_monotonic
                    >= self.settings.feedback_display_s
                ):
                    self._reset_cycle(require_empty=False)
                    self.lifecycle = Lifecycle.WAITING
                    self.reason = DecisionReason.WAITING_FOR_GARMENT
                    return self._snapshot()
                return None

            # Removing a completed garment is part of inspecting it, so keep
            # its result and feedback controls visible while the box is empty.
            # Once another garment is placed in the box, close the unanswered
            # inspection as "nothing found" and let this report start the next
            # measurement cycle.
            if not self.result_removed:
                # One near-zero report is enough to establish the transition:
                # a completed garment is always above the configured minimum
                # garment weight, and waiting for the normal empty-confirmation
                # window could miss a quick remove-and-replace operation.
                if abs(weight_g) <= self.settings.empty_weight_max_g:
                    self.result_removed = True
                    self.result_removed_monotonic = now_monotonic
                    self.empty_weights.clear()
                return None
            if abs(weight_g) <= self.settings.empty_weight_max_g:
                return None

            self._complete_unanswered_inspection()

        if self.active_cycle is None:
            if abs(weight_g) <= self.settings.empty_weight_max_g:
                self.empty_weights.clear()
                if self.lifecycle is not Lifecycle.WAITING:
                    self.lifecycle = Lifecycle.WAITING
                    self.reason = DecisionReason.WAITING_FOR_GARMENT
                    return self._snapshot()
                return None
            self.active_cycle = ActiveCycle(
                cycle_id=str(uuid4()),
                started_at=observed_at,
                started_monotonic=now_monotonic,
                weights_g=deque(maxlen=self.settings.stability_window_size),
            )
            self.lifecycle = Lifecycle.ACQUIRING
            self.reason = DecisionReason.ACQUIRING_MEASUREMENT

        self._collect(report, observed_at)
        stable, measured_weight_g = self._stable_weight(report.stable)
        tag_count = len(self.active_cycle.tags)
        one_tag_ready = (
            tag_count == 1
            and next(iter(self.active_cycle.tags.values())).read_count
            >= self.settings.minimum_tag_reads
        )

        if stable and (tag_count > 1 or one_tag_ready):
            return self._finalize(
                measured_weight_g,
                stable=True,
                completed_at=observed_at,
                now_monotonic=now_monotonic,
            )
        return self._snapshot(measured_weight_g=measured_weight_g, stable=stable)

    def tick(self, now_monotonic: float | None = None) -> DisplaySnapshot | None:
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        if (
            self.serial_connected
            and self.last_report_monotonic is not None
            and now_monotonic - self.last_report_monotonic > self.settings.serial_stale_after_s
        ):
            if self.reason is DecisionReason.SERIAL_STALE:
                return None
            self._reset_cycle(require_empty=True)
            self.lifecycle = Lifecycle.UNAVAILABLE
            self.reason = DecisionReason.SERIAL_STALE
            return self._snapshot(now_monotonic=now_monotonic)

        if (
            self.pending_epc is not None
            and self.pending_since_monotonic is not None
            and now_monotonic - self.pending_since_monotonic >= self.settings.inspection_timeout_s
        ):
            return self._resolve_pending_as_check(completed_at=utc_now())

        cycle = self.active_cycle
        if (
            cycle is not None
            and self.result is None
            and self.pending_epc is None
            and now_monotonic - cycle.started_monotonic >= self.settings.acquisition_timeout_s
        ):
            stable, measured_weight_g = self._stable_weight(None)
            return self._finalize(
                measured_weight_g,
                stable=stable,
                completed_at=utc_now(),
                now_monotonic=now_monotonic,
            )

        if (
            cycle is not None
            and self.result is not None
            and self.result.decision is Decision.CHECK
            and self.feedback_category is None
            and self.result_removed_monotonic is not None
            and now_monotonic - self.result_removed_monotonic
            >= self.settings.inspection_timeout_s
        ):
            self._complete_unanswered_inspection()
            self.lifecycle = Lifecycle.WAITING
            self.reason = DecisionReason.WAITING_FOR_GARMENT
            return self._snapshot(now_monotonic=now_monotonic)

        if (
            cycle is not None
            and self.result is not None
            and self.feedback_category is not None
            and self.result_removed
            and self.feedback_recorded_monotonic is not None
            and now_monotonic - self.feedback_recorded_monotonic
            >= self.settings.feedback_display_s
        ):
            self._reset_cycle(require_empty=False)
            self.lifecycle = Lifecycle.WAITING
            self.reason = DecisionReason.WAITING_FOR_GARMENT
            return self._snapshot(now_monotonic=now_monotonic)

        return None

    def _complete_unanswered_inspection(self) -> None:
        cycle = self.active_cycle
        if cycle is None:  # pragma: no cover - guarded by result lifecycle invariants
            raise RuntimeError("completed result has no active cycle")
        self.repository.add_feedback(
            cycle.cycle_id,
            InspectionRequest(category=InspectionCategory.NOTHING_FOUND),
        )
        self._reset_cycle(require_empty=False)

    def mark_feedback_recorded(
        self,
        cycle_id: str,
        category: InspectionCategory,
        now_monotonic: float | None = None,
    ) -> DisplaySnapshot | None:
        if self.active_cycle is None or self.active_cycle.cycle_id != cycle_id:
            return None
        self.feedback_category = category
        self.feedback_recorded_monotonic = (
            now_monotonic if now_monotonic is not None else time.monotonic()
        )
        return self._snapshot()

    def on_database_error(self) -> DisplaySnapshot:
        self.database_ok = False
        self._reset_cycle(require_empty=True)
        self.lifecycle = Lifecycle.UNAVAILABLE
        self.reason = DecisionReason.DATABASE_ERROR
        return self._snapshot()

    def _observe_empty(self, weight_g: float, firmware_stable: bool | None) -> bool:
        if abs(weight_g) > self.settings.empty_weight_max_g:
            self.empty_weights.clear()
            return False
        self.empty_weights.append(weight_g)
        if len(self.empty_weights) < self.settings.removal_confirm_samples:
            return False
        if firmware_stable is False:
            return False
        if firmware_stable is True:
            return True
        return (
            max(self.empty_weights) - min(self.empty_weights) <= self.settings.stability_tolerance_g
        )

    def _collect(self, report: TeensyReport, observed_at: datetime) -> None:
        cycle = self.active_cycle
        if cycle is None or report.weight_g is None:
            return
        cycle.weights_g.append(report.weight_g)
        cycle.calibration_version = report.calibration_version or cycle.calibration_version
        # Latch metal for the whole cycle: a single detection at any point during
        # acquisition is enough to flag the garment. Gated so a disabled or
        # provisional detector has no effect on the decision or the UI.
        if self.settings.metal_check_enabled and report.metal:
            cycle.metal_detected = True
        for tag in report.tags:
            stat = cycle.tags.get(tag.epc)
            if stat is None:
                stat = MutableTagStat(
                    epc=tag.epc,
                    first_seen_at=observed_at,
                    last_seen_at=observed_at,
                )
                cycle.tags[tag.epc] = stat
            stat.observe(observed_at, tag.rssi)

    def _stable_weight(self, firmware_stable: bool | None) -> tuple[bool, float | None]:
        cycle = self.active_cycle
        if cycle is None or not cycle.weights_g:
            return False, None
        measured = sum(cycle.weights_g) / len(cycle.weights_g)
        if firmware_stable is True:
            return True, measured
        if firmware_stable is False:
            return False, measured
        if len(cycle.weights_g) < self.settings.stability_window_size:
            return False, measured
        spread = max(cycle.weights_g) - min(cycle.weights_g)
        return spread <= self.settings.stability_tolerance_g, measured

    def _decision_epcs(self) -> tuple[str, ...]:
        cycle = self.active_cycle
        if cycle is None:
            return ()
        if len(cycle.tags) > 1:
            return tuple(sorted(cycle.tags))
        return tuple(
            stat.epc
            for stat in cycle.tags.values()
            if stat.read_count >= self.settings.minimum_tag_reads
        )

    def _finalize(
        self,
        measured_weight_g: float | None,
        *,
        stable: bool,
        completed_at: datetime,
        now_monotonic: float,
    ) -> DisplaySnapshot:
        cycle = self.active_cycle
        if cycle is None:
            raise RuntimeError("cannot finalize without an active cycle")

        try:
            epcs = self._decision_epcs()
            garment = self.repository.garment_by_epc(epcs[0]) if len(epcs) == 1 else None
        except Exception:
            logger.exception("database lookup failed while finalizing measurement cycle")
            return self.on_database_error()

        result = evaluate_cycle(
            epcs=epcs,
            measured_weight_g=measured_weight_g,
            stable=stable,
            garment=garment,
            settings=self.settings,
            metal=cycle.metal_detected,
        )
        # A single, stable, in-range but unknown tag is a candidate for on-station
        # registration: hold it on a prompt instead of recording a CHECK now. Any
        # non-answer (dismiss, removal, or timeout) still falls back to CHECK, so
        # the fail-closed guarantee is preserved.
        if result.reason is DecisionReason.UNKNOWN_TAG:
            return self._enter_new_garment_prompt(measured_weight_g, now_monotonic)
        return self._commit_result(result, stable=stable, completed_at=completed_at)

    def _commit_result(
        self, result: DecisionResult, *, stable: bool, completed_at: datetime
    ) -> DisplaySnapshot:
        cycle = self.active_cycle
        if cycle is None:
            raise RuntimeError("cannot commit a result without an active cycle")
        try:
            write = CycleWrite(
                cycle_id=cycle.cycle_id,
                started_at=cycle.started_at,
                completed_at=completed_at,
                garment_id=result.garment.garment_id if result.garment else None,
                reference_id=result.garment.reference_id if result.garment else None,
                measured_weight_mg=result.measured_weight_mg,
                reference_weight_mg=result.reference_weight_mg,
                difference_mg=result.difference_mg,
                threshold_mg=round(self.settings.threshold_g * 1_000),
                decision=result.decision.value,
                reason=result.reason.value,
                metal_detected=cycle.metal_detected,
                protocol_version=1,
                algorithm_version=self.settings.algorithm_version,
                calibration_version=cycle.calibration_version,
                tags=tuple(stat.freeze() for stat in cycle.tags.values()),
            )
            self.repository.persist_cycle(self.context, write)
        except Exception:
            logger.exception("database operation failed while finalizing measurement cycle")
            return self.on_database_error()

        self.result = result
        self.result_garment = result.garment
        if result.garment is not None:
            self.scanned_count += 1
        self.lifecycle = Lifecycle.PASS if result.decision is Decision.PASS else Lifecycle.CHECK
        self.reason = result.reason
        return self._snapshot(stable=stable)

    def _enter_new_garment_prompt(
        self, measured_weight_g: float | None, now_monotonic: float
    ) -> DisplaySnapshot:
        cycle = self.active_cycle
        if cycle is None:
            raise RuntimeError("cannot prompt without an active cycle")
        self.pending_epc = self._decision_epcs()[0]
        self.pending_measured_weight_g = measured_weight_g
        self.pending_since_monotonic = now_monotonic
        self.lifecycle = Lifecycle.NEW_GARMENT
        self.reason = DecisionReason.NEW_GARMENT_DETECTED
        return self._snapshot(measured_weight_g=measured_weight_g, stable=True)

    def _resolve_pending_as_check(self, *, completed_at: datetime) -> DisplaySnapshot:
        cycle = self.active_cycle
        if cycle is None or self.pending_epc is None:
            raise RuntimeError("no pending garment to resolve")
        epc = self.pending_epc
        measured = self.pending_measured_weight_g
        self._clear_pending()
        result = evaluate_cycle(
            epcs=(epc,),
            measured_weight_g=measured,
            stable=True,
            garment=None,
            settings=self.settings,
            metal=cycle.metal_detected,
        )
        return self._commit_result(result, stable=True, completed_at=completed_at)

    def register_new_garment(
        self, cycle_id: str, *, product_name: str | None, wearer_name: str | None
    ) -> DisplaySnapshot | None:
        cycle = self.active_cycle
        if cycle is None or self.pending_epc is None or cycle.cycle_id != cycle_id:
            return None
        epc = self.pending_epc
        measured = self.pending_measured_weight_g
        try:
            self.repository.register_garment(
                epc=epc,
                weight_mg=round(measured * 1_000) if measured is not None else 0,
                product_name=product_name,
                wearer_name=wearer_name,
                calibration_version=cycle.calibration_version,
            )
            garment = self.repository.garment_by_epc(epc)
        except GarmentAlreadyExists:
            raise
        except Exception:
            logger.exception("garment registration failed; station forced unavailable")
            self._clear_pending()
            return self.on_database_error()
        self._clear_pending()
        # The measured weight became this garment's clean reference, so a healthy
        # capture re-evaluates to PASS; metal on the plate still forces a CHECK.
        result = evaluate_cycle(
            epcs=(epc,),
            measured_weight_g=measured,
            stable=True,
            garment=garment,
            settings=self.settings,
            metal=cycle.metal_detected,
        )
        return self._commit_result(result, stable=True, completed_at=utc_now())

    def dismiss_new_garment(self, cycle_id: str) -> DisplaySnapshot | None:
        cycle = self.active_cycle
        if cycle is None or self.pending_epc is None or cycle.cycle_id != cycle_id:
            return None
        return self._resolve_pending_as_check(completed_at=utc_now())

    def _clear_pending(self) -> None:
        self.pending_epc = None
        self.pending_measured_weight_g = None
        self.pending_since_monotonic = None

    def _reset_cycle(self, *, require_empty: bool) -> None:
        self.active_cycle = None
        self.result = None
        self.result_garment = None
        self.result_removed = False
        self.result_removed_monotonic = None
        self.feedback_category = None
        self.feedback_recorded_monotonic = None
        self._clear_pending()
        self.empty_weights.clear()
        self.needs_empty = require_empty

    def _health(self, now_monotonic: float | None = None) -> HealthSnapshot:
        now_monotonic = now_monotonic if now_monotonic is not None else time.monotonic()
        fresh = (
            self.serial_connected
            and self.last_report_monotonic is not None
            and now_monotonic - self.last_report_monotonic <= self.settings.serial_stale_after_s
        )
        return HealthSnapshot(
            backend_ok=True,
            database_ok=self.database_ok,
            serial_connected=self.serial_connected,
            serial_fresh=fresh,
            rfid_ok=self.rfid_ok,
            scale_ok=self.scale_ok,
        )

    def _snapshot(
        self,
        *,
        measured_weight_g: float | None = None,
        stable: bool = False,
        now_monotonic: float | None = None,
    ) -> DisplaySnapshot:
        garment = self.result_garment
        reference_mg = None
        difference_mg = None
        decision = None
        cycle_id = self.active_cycle.cycle_id if self.active_cycle else None
        metal_detected = self.active_cycle.metal_detected if self.active_cycle else False

        if self.result is not None:
            decision = self.result.decision
            measured_mg = self.result.measured_weight_mg
            reference_mg = self.result.reference_weight_mg
            difference_mg = self.result.difference_mg
            measured_weight_g = measured_mg / 1_000 if measured_mg is not None else None

        measurement = None
        if measured_weight_g is not None or reference_mg is not None:
            measurement = MeasurementSnapshot(
                reference_g=reference_mg / 1_000 if reference_mg is not None else None,
                measured_g=measured_weight_g,
                difference_g=difference_mg / 1_000 if difference_mg is not None else None,
                threshold_g=self.settings.threshold_g,
                stable=stable,
            )

        return DisplaySnapshot(
            revision=0,
            updated_at=utc_now(),
            lifecycle=self.lifecycle,
            cycle_id=cycle_id,
            decision=decision,
            reason=self.reason,
            scanned_count=self.scanned_count,
            station=self.context.station,
            operator=self.context.operator,
            garment=garment.garment if garment else None,
            measurement=measurement,
            metal_detected=metal_detected,
            pending_epc=self.pending_epc,
            health=self._health(now_monotonic),
            feedback_recorded=self.feedback_category is not None,
            feedback_category=self.feedback_category,
        )
