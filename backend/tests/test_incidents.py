
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import (
    Incident,
    IncidentStatus,
    Order,
    OrderSource,
    OrderStatus,
)


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_old_pending_order():
    return Order(
        paypal_order_id="TEST-INCIDENT-ORDER",
        amount=Decimal("12.50"),
        currency="USD",
        status=OrderStatus.PENDING,
        source=OrderSource.PAYPAL_SANDBOX,
        idempotency_key="test-incident-api-key",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )


def test_list_incidents_returns_empty_list(client):
    response = client.get("/api/incidents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_incidents_returns_saved_incident(client):
    # Create an incident through the detection endpoint.
    response = client.post("/api/incidents/scan")

    assert response.status_code == 200

    # No orders exist, so the scan should create no incidents.
    assert response.json() == []

    response = client.get("/api/incidents")
    assert response.status_code == 200
    assert response.json() == []


def test_scan_creates_pending_timeout_incident(client):
    # Insert an old pending order using the test database.
    override = app.dependency_overrides[get_db]
    generator = override()
    db = next(generator)

    try:
        db.add(create_old_pending_order())
        db.commit()
    finally:
        generator.close()

    response = client.post("/api/incidents/scan")

    assert response.status_code == 200
    assert any(
        incident["rule_id"] == "PENDING_ORDER_TIMEOUT"
        for incident in response.json()
    )

    listed = client.get("/api/incidents")
    assert listed.status_code == 200
    assert any(
        incident["rule_id"] == "PENDING_ORDER_TIMEOUT"
        for incident in listed.json()
    )


def test_repeated_scans_do_not_duplicate_incidents(client):
    override = app.dependency_overrides[get_db]
    generator = override()
    db = next(generator)

    try:
        db.add(create_old_pending_order())
        db.commit()
    finally:
        generator.close()

    first = client.post("/api/incidents/scan")
    second = client.post("/api/incidents/scan")
    listed = client.get("/api/incidents")

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.json()) == 1
    assert second.json() == []
    assert len(listed.json()) == 1


def test_filter_incidents_by_status(client):
    response = client.get("/api/incidents", params={"status": "open"})

    assert response.status_code == 200
    assert response.json() == []

    invalid = client.get("/api/incidents", params={"status": "INVALID"})
    assert invalid.status_code == 422
