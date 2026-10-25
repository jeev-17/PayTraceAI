from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OrderStatus(str, Enum):
    CREATED = "created"
    APPROVED = "approved"
    PENDING = "pending"
    COMPLETED = "completed"
    DECLINED = "declined"
    VOIDED = "voided"
    UNKNOWN = "unknown"


class OrderSource(str, Enum):
    PAYPAL_SANDBOX = "paypal_sandbox"
    SIMULATED = "simulated"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class IncidentStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


def enum_column(enum_type: type[Enum]) -> SQLAlchemyEnum:
    return SQLAlchemyEnum(
        enum_type,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
    )


class Order(Base):
    __tablename__ = "orders"
    idempotency_key: Mapped[str | None] = mapped_column(
    String(128),
    unique=True,
    nullable=True,
    index=True,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paypal_order_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus))
    source: Mapped[OrderSource] = mapped_column(enum_column(OrderSource))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_verified_status: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("source", "paypal_event_id", name="uq_event_source_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paypal_event_id: Mapped[str] = mapped_column(String(128))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    paypal_order_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128))
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[OrderSource] = mapped_column(enum_column(OrderSource))
    delivery_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_column(VerificationStatus)
    )
    is_duplicate_delivery: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(IncidentStatus), default=IncidentStatus.OPEN
    )
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    evidence_event_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True)


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    details_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
