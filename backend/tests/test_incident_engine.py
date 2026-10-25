
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Incident,
    Order,
    OrderSource,
    OrderStatus,
    PaymentEvent,
    VerificationStatus,
)
from app.services.incident_engine import detect_incidents


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def make_order(db, status=OrderStatus.PENDING):
    order = Order(
        paypal_order_id="TEST-ORDER-001",
        amount=Decimal("12.50"),
        currency="USD",
        status=status,
        source=OrderSource.PAYPAL_SANDBOX,
        idempotency_key="test-incident-order-001",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def make_event(db, order=None, order_ref="TEST-ORDER-001"):
    event = PaymentEvent(
        paypal_event_id="TEST-EVENT-001",
        order_id=order.id if order else None,
        paypal_order_ref=order_ref,
        event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_id="TEST-CAPTURE-001",
        source=OrderSource.PAYPAL_SANDBOX,
        verification_status=VerificationStatus.VERIFIED,
        is_duplicate_delivery=False,
        payload_json={"test": True},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def test_pending_order_creates_timeout_incident(db):
    make_order(db)

    incidents = detect_incidents(db)

    assert any(
        incident.rule_id == "PENDING_ORDER_TIMEOUT"
        for incident in incidents
    )


def test_repeated_scan_does_not_duplicate_pending_incident(db):
    make_order(db)

    first = detect_incidents(db)
    db.commit()
    second = detect_incidents(db)
    db.commit()

    assert len([
        incident for incident in first
        if incident.rule_id == "PENDING_ORDER_TIMEOUT"
    ]) == 1
    assert not any(
        incident.rule_id == "PENDING_ORDER_TIMEOUT"
        for incident in second
    )
    assert db.query(Incident).count() == 1


def test_capture_event_conflicting_with_local_status_creates_incident(db):
    order = make_order(db, status=OrderStatus.APPROVED)
    make_event(db, order=order)

    incidents = detect_incidents(db)

    assert any(
        incident.rule_id == "CAPTURE_STATUS_MISMATCH"
        for incident in incidents
    )


def test_verified_event_for_unknown_order_creates_incident(db):
    make_event(db, order=None, order_ref="UNKNOWN-PAYPAL-ORDER")

    incidents = detect_incidents(db)

    assert any(
        incident.rule_id == "UNMATCHED_PAYMENT_EVENT"
        for incident in incidents
    )


def test_completed_local_order_does_not_trigger_capture_mismatch(db):
    order = make_order(db, status=OrderStatus.COMPLETED)
    make_event(db, order=order)

    incidents = detect_incidents(db)

    assert not any(
        incident.rule_id == "CAPTURE_STATUS_MISMATCH"
        for incident in incidents
    )
