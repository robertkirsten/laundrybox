from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from argus_backend.config import Settings
from argus_backend.decision import evaluate_cycle
from argus_backend.repository import GarmentLookup
from argus_backend.schemas import (
    Decision,
    DecisionReason,
    GarmentSnapshot,
    TeensyMessage,
)

EPC = "E28011052000773410000001"


def garment_lookup(reference_weight_mg: int | None = 240_000) -> GarmentLookup:
    return GarmentLookup(
        garment_id=1,
        reference_id=1 if reference_weight_mg is not None else None,
        reference_weight_mg=reference_weight_mg,
        garment=GarmentSnapshot(
            epc=EPC,
            chute_number=911,
            id_number="77341",
            article_number="A-5521",
            product_name="Hose Blau",
            size="L",
            customer_name="Müller & Co.",
            customer_number="K-20441",
            wearer_name="Sabine Weber",
            wearer_number="T-8821",
            manufacture_year=2020,
            manufacture_week=8,
        ),
    )


def test_teensy_schema_normalizes_epc_and_forbids_unknown_fields() -> None:
    adapter = TypeAdapter(TeensyMessage)
    report = adapter.validate_python(
        {
            "v": 1,
            "t": 10,
            "raw": 123,
            "weight_g": 240.0,
            "tags": [{"epc": EPC.lower(), "rssi": 87}],
        }
    )
    assert report.tags[0].epc == EPC

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "v": 1,
                "t": 10,
                "raw": 123,
                "weight_g": 240.0,
                "tags": [],
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"v": 1, "t": 10, "raw": 123, "weight_g": 240.0, "tags": [{"epc": "XYZ", "rssi": 1}]}
        )


@pytest.mark.parametrize("weight_g", [237.0, 243.0])
def test_threshold_is_inclusive_at_three_grams(weight_g: float) -> None:
    result = evaluate_cycle(
        epcs=(EPC,),
        measured_weight_g=weight_g,
        stable=True,
        garment=garment_lookup(),
        settings=Settings(_env_file=None, threshold_g=3.0),
    )
    assert result.decision is Decision.PASS
    assert result.reason is DecisionReason.WITHIN_THRESHOLD


@pytest.mark.parametrize("weight_g", [236.999, 243.001])
def test_threshold_failure_outside_three_grams(weight_g: float) -> None:
    result = evaluate_cycle(
        epcs=(EPC,),
        measured_weight_g=weight_g,
        stable=True,
        garment=garment_lookup(),
        settings=Settings(_env_file=None, threshold_g=3.0),
    )
    assert result.decision is Decision.CHECK
    assert result.reason is DecisionReason.DIFFERENCE_EXCEEDED


@pytest.mark.parametrize(
    ("epcs", "garment", "expected"),
    [
        ((), None, DecisionReason.MISSING_TAG),
        ((EPC, "E28011052000773420000002"), None, DecisionReason.MULTIPLE_TAGS),
        (("E28000000000000000000000",), None, DecisionReason.UNKNOWN_TAG),
        ((EPC,), garment_lookup(None), DecisionReason.MISSING_REFERENCE),
    ],
)
def test_unsafe_identification_cases_require_check(
    epcs: tuple[str, ...],
    garment: GarmentLookup | None,
    expected: DecisionReason,
) -> None:
    result = evaluate_cycle(
        epcs=epcs,
        measured_weight_g=240.0,
        stable=True,
        garment=garment,
        settings=Settings(_env_file=None),
    )
    assert result.decision is Decision.CHECK
    assert result.reason is expected
