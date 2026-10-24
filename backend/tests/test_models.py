from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, normalize_database_url
from app.models import (
    AuditRecord,
    Incident,
    IncidentStatus,
    Order,
    OrderSource,
    OrderStatus,
    PaymentEvent,
    VerificationStatus,
)


def test_postgres_urls_use_psycopg_driver() -> None:
    assert (
        normalize_database_url("postgres://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host/db")
        == "postgresql+psycopg://user:pass@host/db"
    )


def test_all_models_can_be_created_and_persisted() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        order = Order(
            paypal_order_id="sandbox-order-1",
            amount=Decimal("12.50"),
            currency="USD",
            status=OrderStatus.CREATED,
            source=OrderSource.SIMULATED,
        )
        session.add(order)
        session.flush()

        event = PaymentEvent(
            paypal_event_id="event-1",
            order_id=order.id,
            event_type="TEST.EVENT",
            source=OrderSource.SIMULATED,
            verification_status=VerificationStatus.NOT_APPLICABLE,
            payload_json={"source": "simulated"},
        )
        incident = Incident(
            rule_id="STATE_MISMATCH",
            severity="medium",
            status=IncidentStatus.OPEN,
            order_id=order.id,
            evidence_event_ids=[],
            description="Test incident",
            dedup_key="test-incident-1",
        )
        audit = AuditRecord(
            timestamp=datetime.now(timezone.utc),
            actor="test",
            action="created",
            entity_type="order",
            entity_id=str(order.id),
            details_json={},
        )
        session.add_all([event, incident, audit])
        session.commit()

        assert session.get(Order, order.id) is not None
        assert session.get(PaymentEvent, event.id) is not None
        assert session.get(Incident, incident.id) is not None
        assert session.get(AuditRecord, audit.id) is not None
