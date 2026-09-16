from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_number: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_number: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))


class Wearer(Base):
    __tablename__ = "wearers"

    id: Mapped[int] = mapped_column(primary_key=True)
    wearer_number: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))

    customer: Mapped[Customer] = relationship()


class Garment(Base):
    __tablename__ = "garments"

    id: Mapped[int] = mapped_column(primary_key=True)
    epc: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    chute_number: Mapped[int] = mapped_column(Integer)
    id_number: Mapped[str] = mapped_column(String(64), unique=True)
    article_number: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(160))
    size: Mapped[str] = mapped_column(String(32))
    manufacture_year: Mapped[int] = mapped_column(Integer)
    manufacture_week: Mapped[int] = mapped_column(Integer)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    wearer_id: Mapped[int] = mapped_column(ForeignKey("wearers.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    customer: Mapped[Customer] = relationship()
    wearer: Mapped[Wearer] = relationship()
    references: Mapped[list[GarmentReference]] = relationship(back_populates="garment")


class GarmentReference(Base):
    __tablename__ = "garment_references"
    __table_args__ = (
        Index(
            "uq_active_garment_reference",
            "garment_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    garment_id: Mapped[int] = mapped_column(ForeignKey("garments.id"), index=True)
    weight_mg: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(64), default="seed")
    calibration_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    garment: Mapped[Garment] = relationship(back_populates="references")


class ConfigurationHistory(Base):
    __tablename__ = "configuration_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    threshold_mg: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScanCycle(Base):
    __tablename__ = "scan_cycles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"))
    garment_id: Mapped[int | None] = mapped_column(ForeignKey("garments.id"), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("garment_references.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    measured_weight_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_weight_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    difference_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threshold_mg: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(64))
    protocol_version: Mapped[int] = mapped_column(Integer, default=1)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    calibration_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    garment: Mapped[Garment | None] = relationship()
    reference: Mapped[GarmentReference | None] = relationship()
    observations: Mapped[list[TagObservationRecord]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan"
    )
    feedback: Mapped[InspectionFeedback | None] = relationship(
        back_populates="cycle", cascade="all, delete-orphan", uselist=False
    )


class TagObservationRecord(Base):
    __tablename__ = "tag_observations"
    __table_args__ = (UniqueConstraint("cycle_id", "epc", name="uq_cycle_epc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("scan_cycles.id"), index=True)
    epc: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_count: Mapped[int] = mapped_column(Integer)
    max_rssi: Mapped[int] = mapped_column(Integer)

    cycle: Mapped[ScanCycle] = relationship(back_populates="observations")


class InspectionFeedback(Base):
    __tablename__ = "inspection_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("scan_cycles.id"), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    cycle: Mapped[ScanCycle] = relationship(back_populates="feedback")
