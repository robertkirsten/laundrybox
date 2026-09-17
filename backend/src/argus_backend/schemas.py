from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

ModelConfig = ConfigDict(extra="ignore", allow_inf_nan=False)
StrictInputModelConfig = ConfigDict(extra="forbid", allow_inf_nan=False)
Epc = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=2, max_length=64),
]


class TagObservation(BaseModel):
    model_config = ModelConfig

    epc: Epc
    rssi: int = Field(ge=0, le=255)

    @field_validator("epc")
    @classmethod
    def validate_epc(cls, value: str) -> str:
        if len(value) % 2 or any(character not in "0123456789ABCDEF" for character in value):
            raise ValueError("EPC must contain an even number of hexadecimal characters")
        return value


class GarmentSeed(BaseModel):
    """Validated row from the operator-editable mock garment CSV."""

    model_config = StrictInputModelConfig

    epc: Epc
    chute_number: int = Field(gt=0)
    id_number: str = Field(min_length=1, max_length=64)
    article_number: str = Field(min_length=1, max_length=64)
    product_name: str = Field(min_length=1, max_length=160)
    size: str = Field(min_length=1, max_length=32)
    manufacture_year: int = Field(ge=1900, le=2200)
    manufacture_week: int = Field(ge=1, le=53)
    customer_number: str = Field(min_length=1, max_length=64)
    customer_name: str = Field(min_length=1, max_length=160)
    wearer_number: str = Field(min_length=1, max_length=64)
    wearer_name: str = Field(min_length=1, max_length=160)
    reference_weight_g: float = Field(gt=0)
    source: str = Field(min_length=1, max_length=64)
    calibration_version: str | None = Field(default=None, max_length=64)

    @field_validator("epc")
    @classmethod
    def validate_epc(cls, value: str) -> str:
        if len(value) % 2 or any(character not in "0123456789ABCDEF" for character in value):
            raise ValueError("EPC must contain an even number of hexadecimal characters")
        return value


class TeensyReport(BaseModel):
    model_config = ModelConfig

    v: Literal[1]
    t: int = Field(ge=0)
    raw: int | None
    weight_g: float | None
    tags: list[TagObservation] = Field(max_length=64)
    stable: bool | None = None
    metal: bool | None = None
    auto_tare: bool = False
    tare_residual_g: float | None = None
    load_cells_g: list[float] | None = Field(default=None, max_length=8)
    calibration_version: str | None = Field(default=None, max_length=64)


class TeensyEvent(BaseModel):
    model_config = ModelConfig

    v: Literal[1]
    event: Literal["boot", "rfid_config_error"]
    step: str | None = Field(default=None, max_length=64)


TeensyMessage = TeensyReport | TeensyEvent


class Lifecycle(StrEnum):
    STARTING = "starting"
    WAITING = "waiting"
    ACQUIRING = "acquiring"
    PASS = "pass"
    CHECK = "check"
    UNAVAILABLE = "unavailable"


class Decision(StrEnum):
    PASS = "PASS"
    CHECK = "CHECK"


class DecisionReason(StrEnum):
    WITHIN_THRESHOLD = "within_threshold"
    DIFFERENCE_EXCEEDED = "difference_exceeded"
    METAL_DETECTED = "metal_detected"
    MISSING_TAG = "missing_tag"
    MULTIPLE_TAGS = "multiple_tags"
    UNKNOWN_TAG = "unknown_tag"
    MISSING_REFERENCE = "missing_reference"
    MISSING_WEIGHT = "missing_weight"
    UNSTABLE_WEIGHT = "unstable_weight"
    IMPLAUSIBLE_WEIGHT = "implausible_weight"
    ACQUISITION_TIMEOUT = "acquisition_timeout"
    SERIAL_DISCONNECTED = "serial_disconnected"
    SERIAL_STALE = "serial_stale"
    TEENSY_RESTARTED = "teensy_restarted"
    RFID_CONFIGURATION_ERROR = "rfid_configuration_error"
    REMOVE_GARMENT_AFTER_RESTART = "remove_garment_after_restart"
    DATABASE_ERROR = "database_error"
    WAITING_FOR_EMPTY_BOX = "waiting_for_empty_box"
    WAITING_FOR_GARMENT = "waiting_for_garment"
    ACQUIRING_MEASUREMENT = "acquiring_measurement"


class HealthSnapshot(BaseModel):
    model_config = ModelConfig

    backend_ok: bool = True
    database_ok: bool = True
    serial_connected: bool = False
    serial_fresh: bool = False
    rfid_ok: bool = False
    scale_ok: bool = False


class StationSnapshot(BaseModel):
    model_config = ModelConfig

    code: str
    name: str


class OperatorSnapshot(BaseModel):
    model_config = ModelConfig

    number: str
    display_name: str


class GarmentSnapshot(BaseModel):
    model_config = ModelConfig

    epc: str
    chute_number: int
    id_number: str
    article_number: str
    product_name: str
    size: str
    customer_name: str
    customer_number: str
    wearer_name: str
    wearer_number: str
    manufacture_year: int
    manufacture_week: int


class MeasurementSnapshot(BaseModel):
    model_config = ModelConfig

    reference_g: float | None
    measured_g: float | None
    difference_g: float | None
    threshold_g: float
    stable: bool


class InspectionCategory(StrEnum):
    NOTHING_FOUND = "nothing_found"
    SCISSORS = "scissors"
    KEYS = "keys"
    MONEY = "money"
    PAPER = "paper"
    PEN = "pen"
    TISSUES = "tissues"
    HEADPHONES = "headphones"
    TOOL = "tool"
    OTHER = "other"


class DisplaySnapshot(BaseModel):
    model_config = ModelConfig

    revision: int = Field(ge=0)
    updated_at: datetime
    lifecycle: Lifecycle
    cycle_id: str | None = None
    decision: Decision | None = None
    reason: DecisionReason
    scanned_count: int = Field(ge=0)
    station: StationSnapshot
    operator: OperatorSnapshot
    garment: GarmentSnapshot | None = None
    measurement: MeasurementSnapshot | None = None
    # Ferrous metal seen at any point during the current cycle. A minor,
    # secondary indicator: weight is the primary detection method, but metal on
    # its own is enough to force a CHECK (see evaluate_cycle).
    metal_detected: bool = False
    health: HealthSnapshot
    feedback_recorded: bool = False
    feedback_category: InspectionCategory | None = None


class InspectionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        json_schema_extra={"examples": [{"category": "keys", "note": "Found in right pocket"}]},
    )

    category: InspectionCategory
    note: str | None = Field(default=None, max_length=500)


class InspectionResponse(BaseModel):
    model_config = ModelConfig

    cycle_id: str
    category: InspectionCategory
    recorded_at: datetime
    duplicate: bool = False


class HealthResponse(BaseModel):
    model_config = ModelConfig

    status: Literal["ok", "degraded"]
    version: str
    health: HealthSnapshot


class DebugIngestRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        json_schema_extra={
            "examples": [
                {
                    "message": {
                        "v": 1,
                        "t": 1250,
                        "raw": 340100,
                        "weight_g": 240.1,
                        "tags": [{"epc": "E28011052000773410000001", "rssi": 210}],
                    }
                }
            ]
        },
    )

    message: dict[str, object]
