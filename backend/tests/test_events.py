
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Order,
    OrderSource,
    OrderStatus,
    PaymentEvent,
    VerificationStatus,
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client, TestSessionLocal
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def create_test_event(
    session,
    paypal_event_id,
    event_type="PAYMENT.CAPTURE.COMPLETED",
    source=OrderSource.PAYPAL_SANDBOX,
    order_id=None,
):
    event = PaymentEvent(
        paypal_event_id=paypal_event_id,
        order_id=order_id,
        paypal_order_ref="TEST-PAYPAL-ORDER",
        event_type=event_type,
        resource_id="TEST-CAPTURE",
        source=source,
        delivery_received_at=datetime.now(timezone.utc),
        event_created_at=datetime.now(timezone.utc),
        verification_status=VerificationStatus.VERIFIED,
        is_duplicate_delivery=False,
        payload_json={"private": "must not be returned"},
        processed_at=datetime.now(timezone.utc),
    )

    session.add(event)
    session.commit()
    return event


def test_list_events_returns_empty_list(client):
    test_client, _ = client

    response = test_client.get("/api/events")

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []



def test_list_events_returns_metadata_without_raw_payload(client):
    test_client, session_factory = client

    with session_factory() as session:
        event = create_test_event(session, "WH-TEST-001")
        event_id = event.id

    response = test_client.get("/api/events")

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1

    returned_event = data["items"][0]

    assert returned_event["id"] == event_id
    assert returned_event["paypal_event_id"] == "WH-TEST-001"
    assert returned_event["event_type"] == "PAYMENT.CAPTURE.COMPLETED"
    assert returned_event["verification_status"] == "verified"
    assert returned_event["is_duplicate_delivery"] is False

    assert "payload_json" not in returned_event
    assert "private" not in str(returned_event)


def test_list_events_filters_by_event_type(client):
    test_client, session_factory = client

    with session_factory() as session:
        create_test_event(session, "WH-TEST-002")
        create_test_event(
            session,
            "WH-TEST-003",
            event_type="PAYMENT.CAPTURE.PENDING",
        )

    response = test_client.get(
        "/api/events",
        params={"event_type": "PAYMENT.CAPTURE.PENDING"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["paypal_event_id"] == "WH-TEST-003"


def test_list_events_filters_by_source(client):
    test_client, session_factory = client

    with session_factory() as session:
        create_test_event(session, "WH-TEST-004")
        create_test_event(
            session,
            "SIM-TEST-001",
            source=OrderSource.SIMULATED,
        )

    response = test_client.get(
        "/api/events",
        params={"source": "simulated"},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["source"] == "simulated"


def test_list_events_rejects_unsupported_source(client):
    test_client, _ = client

    response = test_client.get(
        "/api/events",
        params={"source": "invalid-source"},
    )

    assert response.status_code == 400


def test_list_events_supports_pagination(client):
    test_client, session_factory = client

    with session_factory() as session:
        create_test_event(session, "WH-TEST-005")
        create_test_event(session, "WH-TEST-006")
        create_test_event(session, "WH-TEST-007")

    response = test_client.get(
        "/api/events",
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["limit"] == 2
    assert response.json()["offset"] == 1
    assert len(response.json()["items"]) == 2