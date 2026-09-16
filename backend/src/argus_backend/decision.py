from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .config import Settings
from .repository import GarmentLookup
from .schemas import Decision, DecisionReason


@dataclass(frozen=True)
class DecisionResult:
    decision: Decision
    reason: DecisionReason
    measured_weight_mg: int | None
    reference_weight_mg: int | None
    difference_mg: int | None
    garment: GarmentLookup | None


def evaluate_cycle(
    *,
    epcs: tuple[str, ...],
    measured_weight_g: float | None,
    stable: bool,
    garment: GarmentLookup | None,
    settings: Settings,
) -> DecisionResult:
    measured_mg = (
        round(measured_weight_g * 1_000)
        if measured_weight_g is not None and isfinite(measured_weight_g)
        else None
    )

    if measured_mg is None:
        return DecisionResult(
            Decision.CHECK, DecisionReason.MISSING_WEIGHT, None, None, None, garment
        )
    if not stable:
        return DecisionResult(
            Decision.CHECK,
            DecisionReason.UNSTABLE_WEIGHT,
            measured_mg,
            None,
            None,
            garment,
        )
    if not settings.min_garment_weight_g <= measured_weight_g <= settings.max_garment_weight_g:
        return DecisionResult(
            Decision.CHECK,
            DecisionReason.IMPLAUSIBLE_WEIGHT,
            measured_mg,
            None,
            None,
            garment,
        )
    if len(epcs) == 0:
        return DecisionResult(
            Decision.CHECK, DecisionReason.MISSING_TAG, measured_mg, None, None, None
        )
    if len(epcs) > 1:
        return DecisionResult(
            Decision.CHECK, DecisionReason.MULTIPLE_TAGS, measured_mg, None, None, None
        )
    if garment is None:
        return DecisionResult(
            Decision.CHECK, DecisionReason.UNKNOWN_TAG, measured_mg, None, None, None
        )
    if garment.reference_weight_mg is None:
        return DecisionResult(
            Decision.CHECK,
            DecisionReason.MISSING_REFERENCE,
            measured_mg,
            None,
            None,
            garment,
        )

    difference_mg = measured_mg - garment.reference_weight_mg
    threshold_mg = round(settings.threshold_g * 1_000)
    if abs(difference_mg) <= threshold_mg:
        decision = Decision.PASS
        reason = DecisionReason.WITHIN_THRESHOLD
    else:
        decision = Decision.CHECK
        reason = DecisionReason.DIFFERENCE_EXCEEDED
    return DecisionResult(
        decision,
        reason,
        measured_mg,
        garment.reference_weight_mg,
        difference_mg,
        garment,
    )
