from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from .config import Settings
from .database import session_scope
from .models import (
    ConfigurationHistory,
    Customer,
    Garment,
    GarmentReference,
    InspectionFeedback,
    Operator,
    ScanCycle,
    Station,
    TagObservationRecord,
    Wearer,
)
from .schemas import (
    GarmentSeed,
    GarmentSnapshot,
    InspectionCategory,
    InspectionRequest,
    InspectionResponse,
    OperatorSnapshot,
    StationSnapshot,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class RepositoryError(RuntimeError):
    pass


class CycleNotFound(RepositoryError):
    pass


class FeedbackConflict(RepositoryError):
    pass


@dataclass(frozen=True)
class RuntimeContext:
    station_id: int
    station: StationSnapshot
    operator_id: int
    operator: OperatorSnapshot


@dataclass(frozen=True)
class GarmentLookup:
    garment_id: int
    reference_id: int | None
    reference_weight_mg: int | None
    garment: GarmentSnapshot


@dataclass(frozen=True)
class TagStat:
    epc: str
    first_seen_at: datetime
    last_seen_at: datetime
    read_count: int
    max_rssi: int


@dataclass(frozen=True)
class ScanLogEntry:
    cycle_id: str
    completed_at: datetime
    epc: str | None
    garment_name: str | None
    measured_weight_g: float | None
    reference_weight_g: float | None


@dataclass(frozen=True)
class CycleWrite:
    cycle_id: str
    started_at: datetime
    completed_at: datetime
    garment_id: int | None
    reference_id: int | None
    measured_weight_mg: int | None
    reference_weight_mg: int | None
    difference_mg: int | None
    threshold_mg: int
    decision: str
    reason: str
    protocol_version: int
    algorithm_version: str
    calibration_version: str | None
    tags: tuple[TagStat, ...]


class Repository:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self._factory = factory
        self._settings = settings

    def seed_mock_data(self) -> None:
        fixtures = self._load_mock_fixtures()
        with session_scope(self._factory) as session:
            station = session.scalar(
                select(Station).where(Station.code == self._settings.station_code)
            )
            if station is None:
                station = Station(code=self._settings.station_code, name="ARGUS Check-Station")
                session.add(station)

            operator = session.scalar(
                select(Operator).where(Operator.employee_number == self._settings.operator_number)
            )
            if operator is None:
                operator = Operator(
                    employee_number=self._settings.operator_number,
                    display_name="M. Weber",
                )
                session.add(operator)

            for fixture in fixtures:
                customer = session.scalar(
                    select(Customer).where(Customer.customer_number == fixture.customer_number)
                )
                if customer is None:
                    customer = Customer(
                        customer_number=fixture.customer_number,
                        name=fixture.customer_name,
                    )
                    session.add(customer)
                    session.flush()

                wearer = session.scalar(
                    select(Wearer).where(Wearer.wearer_number == fixture.wearer_number)
                )
                if wearer is None:
                    wearer = Wearer(
                        wearer_number=fixture.wearer_number,
                        display_name=fixture.wearer_name,
                        customer_id=customer.id,
                    )
                    session.add(wearer)
                    session.flush()
                elif wearer.customer_id != customer.id:
                    raise RepositoryError(
                        f"wearer {fixture.wearer_number} belongs to a different customer"
                    )

                garment = session.scalar(select(Garment).where(Garment.epc == fixture.epc))
                if garment is None:
                    garment = Garment(
                        epc=fixture.epc,
                        chute_number=fixture.chute_number,
                        id_number=fixture.id_number,
                        article_number=fixture.article_number,
                        product_name=fixture.product_name,
                        size=fixture.size,
                        manufacture_year=fixture.manufacture_year,
                        manufacture_week=fixture.manufacture_week,
                        customer_id=customer.id,
                        wearer_id=wearer.id,
                    )
                    session.add(garment)
                    session.flush()

                active_reference = session.scalar(
                    select(GarmentReference).where(
                        GarmentReference.garment_id == garment.id,
                        GarmentReference.is_active.is_(True),
                    )
                )
                if active_reference is None:
                    session.add(
                        GarmentReference(
                            garment_id=garment.id,
                            weight_mg=round(fixture.reference_weight_g * 1_000),
                            recorded_at=utc_now(),
                            source=fixture.source,
                            calibration_version=fixture.calibration_version,
                        )
                    )

            existing_config = session.scalar(
                select(ConfigurationHistory).where(
                    ConfigurationHistory.algorithm_version == self._settings.algorithm_version,
                    ConfigurationHistory.threshold_mg == round(self._settings.threshold_g * 1_000),
                )
            )
            if existing_config is None:
                session.add(
                    ConfigurationHistory(
                        algorithm_version=self._settings.algorithm_version,
                        threshold_mg=round(self._settings.threshold_g * 1_000),
                        created_at=utc_now(),
                    )
                )

    def _load_mock_fixtures(self) -> tuple[GarmentSeed, ...]:
        path = self._settings.mock_data_path or (
            Path(__file__).parent / "fixtures" / "mock_garments.csv"
        )
        try:
            with path.open(newline="", encoding="utf-8") as csv_file:
                rows = tuple(csv.DictReader(csv_file))
        except OSError as error:
            raise RepositoryError(f"cannot read mock garment CSV {path}: {error}") from error
        if not rows:
            raise RepositoryError(f"mock garment CSV {path} contains no data rows")
        try:
            return tuple(GarmentSeed.model_validate(row) for row in rows)
        except ValidationError as error:
            raise RepositoryError(f"invalid mock garment CSV {path}: {error}") from error

    def runtime_context(self) -> RuntimeContext:
        with session_scope(self._factory) as session:
            station = session.scalar(
                select(Station).where(
                    Station.code == self._settings.station_code,
                    Station.is_active.is_(True),
                )
            )
            operator = session.scalar(
                select(Operator).where(
                    Operator.employee_number == self._settings.operator_number,
                    Operator.is_active.is_(True),
                )
            )
            if station is None or operator is None:
                raise RepositoryError("active station/operator configuration is missing")
            return RuntimeContext(
                station_id=station.id,
                station=StationSnapshot(code=station.code, name=station.name),
                operator_id=operator.id,
                operator=OperatorSnapshot(
                    number=operator.employee_number,
                    display_name=operator.display_name,
                ),
            )

    def garment_by_epc(self, epc: str) -> GarmentLookup | None:
        with session_scope(self._factory) as session:
            garment = session.scalar(
                select(Garment)
                .options(joinedload(Garment.customer), joinedload(Garment.wearer))
                .where(Garment.epc == epc, Garment.is_active.is_(True))
            )
            if garment is None:
                return None
            reference = session.scalar(
                select(GarmentReference).where(
                    GarmentReference.garment_id == garment.id,
                    GarmentReference.is_active.is_(True),
                )
            )
            return GarmentLookup(
                garment_id=garment.id,
                reference_id=reference.id if reference else None,
                reference_weight_mg=reference.weight_mg if reference else None,
                garment=GarmentSnapshot(
                    epc=garment.epc,
                    chute_number=garment.chute_number,
                    id_number=garment.id_number,
                    article_number=garment.article_number,
                    product_name=garment.product_name,
                    size=garment.size,
                    customer_name=garment.customer.name,
                    customer_number=garment.customer.customer_number,
                    wearer_name=garment.wearer.display_name,
                    wearer_number=garment.wearer.wearer_number,
                    manufacture_year=garment.manufacture_year,
                    manufacture_week=garment.manufacture_week,
                ),
            )

    def completed_known_cycle_count(self) -> int:
        with session_scope(self._factory) as session:
            return int(
                session.scalar(
                    select(func.count(ScanCycle.id)).where(ScanCycle.garment_id.is_not(None))
                )
                or 0
            )

    def recent_scan_log(self, limit: int = 20) -> tuple[ScanLogEntry, ...]:
        """Return completed cycles newest first for the operator-facing scan log."""
        with session_scope(self._factory) as session:
            cycles = session.scalars(
                select(ScanCycle)
                .options(joinedload(ScanCycle.garment), selectinload(ScanCycle.observations))
                .order_by(ScanCycle.completed_at.desc(), ScanCycle.id.desc())
                .limit(limit)
            ).all()
            return tuple(
                ScanLogEntry(
                    cycle_id=cycle.id,
                    completed_at=cycle.completed_at,
                    epc=",".join(sorted(item.epc for item in cycle.observations)) or None,
                    garment_name=cycle.garment.product_name if cycle.garment else None,
                    measured_weight_g=(
                        cycle.measured_weight_mg / 1_000
                        if cycle.measured_weight_mg is not None
                        else None
                    ),
                    reference_weight_g=(
                        cycle.reference_weight_mg / 1_000
                        if cycle.reference_weight_mg is not None
                        else None
                    ),
                )
                for cycle in cycles
            )

    def persist_cycle(self, context: RuntimeContext, cycle: CycleWrite) -> None:
        with session_scope(self._factory) as session:
            session.add(
                ScanCycle(
                    id=cycle.cycle_id,
                    station_id=context.station_id,
                    operator_id=context.operator_id,
                    garment_id=cycle.garment_id,
                    reference_id=cycle.reference_id,
                    started_at=cycle.started_at,
                    completed_at=cycle.completed_at,
                    measured_weight_mg=cycle.measured_weight_mg,
                    reference_weight_mg=cycle.reference_weight_mg,
                    difference_mg=cycle.difference_mg,
                    threshold_mg=cycle.threshold_mg,
                    decision=cycle.decision,
                    reason=cycle.reason,
                    protocol_version=cycle.protocol_version,
                    algorithm_version=cycle.algorithm_version,
                    calibration_version=cycle.calibration_version,
                    observations=[
                        TagObservationRecord(
                            epc=tag.epc,
                            first_seen_at=tag.first_seen_at,
                            last_seen_at=tag.last_seen_at,
                            read_count=tag.read_count,
                            max_rssi=tag.max_rssi,
                        )
                        for tag in cycle.tags
                    ],
                )
            )

    def add_feedback(self, cycle_id: str, request: InspectionRequest) -> InspectionResponse:
        with session_scope(self._factory) as session:
            cycle = session.get(ScanCycle, cycle_id)
            if cycle is None:
                raise CycleNotFound(cycle_id)
            existing = session.scalar(
                select(InspectionFeedback).where(InspectionFeedback.cycle_id == cycle_id)
            )
            if existing is not None:
                if existing.category != request.category.value or existing.note != request.note:
                    raise FeedbackConflict("different feedback already exists for this cycle")
                return InspectionResponse(
                    cycle_id=cycle_id,
                    category=InspectionCategory(existing.category),
                    recorded_at=existing.recorded_at,
                    duplicate=True,
                )

            recorded_at = utc_now()
            session.add(
                InspectionFeedback(
                    cycle_id=cycle_id,
                    category=request.category.value,
                    note=request.note,
                    recorded_at=recorded_at,
                )
            )
            return InspectionResponse(
                cycle_id=cycle_id,
                category=request.category,
                recorded_at=recorded_at,
            )

    def feedback_exists(self, cycle_id: str) -> bool:
        with session_scope(self._factory) as session:
            return (
                session.scalar(
                    select(InspectionFeedback.id).where(InspectionFeedback.cycle_id == cycle_id)
                )
                is not None
            )
