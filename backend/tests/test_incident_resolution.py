
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditRecord, Incident, IncidentStatus


@pytest.fixture
def setup_client():
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

    with TestClient(app) as client:
        db = TestingSessionLocal()
        incident = Incident(
            rule_id="TEST_INCIDENT",
            severity="medium",
            status=IncidentStatus.OPEN,
            order_id=None,
            evidence_event_ids=[],
            description="Test incident for resolution.",
            created_at=datetime.now(timezone.utc),
            dedup_key="test-resolution-incident",
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        incident_id = incident.id
        db.close()

        yield client, TestingSessionLocal, incident_id

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_resolve_incident_updates_status_and_audit(setup_client):
    client, SessionLocal, incident_id = setup_client

    response = client.post(
        f"/api/incidents/{incident_id}/resolve",
        json={"resolution_reason": "Verified the order state and reviewed the event."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert response.json()["resolution_reason"] == (
        "Verified the order state and reviewed the event."
    )
    assert response.json()["resolved_at"] is not None

    db = SessionLocal()
    try:
        audit = (
            db.query(AuditRecord)
            .filter(AuditRecord.entity_id == str(incident_id))
            .first()
        )
        assert audit is not None
        assert audit.action == "INCIDENT_RESOLVED"
    finally:
        db.close()


def test_resolve_missing_incident_returns_404(setup_client):
    client, _, _ = setup_client

    response = client.post(
        "/api/incidents/99999/resolve",
        json={"resolution_reason": "Reviewed."},
    )

    assert response.status_code == 404


def test_resolve_incident_rejects_blank_reason(setup_client):
    client, _, incident_id = setup_client

    response = client.post(
        f"/api/incidents/{incident_id}/resolve",
        json={"resolution_reason": "   "},
    )

    assert response.status_code == 422


def test_resolve_incident_rejects_second_resolution(setup_client):
    client, _, incident_id = setup_client
    payload = {"resolution_reason": "Verified the final state."}

    first = client.post(
        f"/api/incidents/{incident_id}/resolve",
        json=payload,
    )
    second = client.post(
        f"/api/incidents/{incident_id}/resolve",
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 409
