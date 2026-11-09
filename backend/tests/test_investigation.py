
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

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
from app.services import investigation_service


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        "app.security.settings.admin_api_key",
        "test-admin-key",
    )

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
        test_client.headers.update(
            {"X-Admin-Key": "test-admin-key"}
        )
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()




def create_incident(db):
    order = Order(
        paypal_order_id="SIM-TEST-ORDER-001",
        amount=Decimal("25.00"),
        currency="USD",
        status=OrderStatus.PENDING,
        source=OrderSource.SIMULATED,
        idempotency_key=None,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    db.add(order)
    db.flush()

    incident = Incident(
        rule_id="PENDING_ORDER_TIMEOUT",
        severity="medium",
        status=IncidentStatus.OPEN,
        order_id=order.id,
        evidence_event_ids=[],
        description="Simulated order remained pending beyond the threshold.",
        dedup_key="test-pending-timeout-001",
    )

    db.add(incident)
    db.commit()

    incident_id = incident.id
    db.close()

    return incident_id


def create_deterministic_report():
    return {
        "question": "Why is this payment still pending?",
        "incident_id": 1,
        "evidence": [],
        "limitations": [],
        "summary": "Deterministic summary",
        "findings": ["Original finding"],
        "hypotheses": ["Original hypothesis"],
        "recommended_checks": ["Verify payment status"],
        "generated_by": "deterministic_fallback",
    }


def configure_openai(monkeypatch, content=None, error=None):
    fake_response = MagicMock()
    fake_response.choices[0].message.content = content

    fake_client = MagicMock()

    if error is not None:
        fake_client.chat.completions.create.side_effect = error
    else:
        fake_client.chat.completions.create.return_value = fake_response

    monkeypatch.setattr(
        investigation_service,
        "settings",
        MagicMock(
            llm_provider="openai",
            llm_api_key="test-key",
            llm_model="test-model",
        ),
    )

    monkeypatch.setattr(
        investigation_service,
        "OpenAI",
        MagicMock(return_value=fake_client),
    )

    return fake_client


def test_investigation_returns_evidence_based_report(client):
    override = app.dependency_overrides[get_db]
    generator = override()
    db = next(generator)

    try:
        incident_id = create_incident(db)
    finally:
        generator.close()

    response = client.post(
        f"/api/incidents/{incident_id}/investigate",
        json={"question": "Why is this order still pending?"},
    )

    assert response.status_code == 200

    report = response.json()

    assert report["incident_id"] == incident_id
    assert report["generated_by"] == "deterministic_fallback"
    assert report["findings"]
    assert report["hypotheses"]
    assert report["recommended_checks"]
    assert report["limitations"]

    assert any(
        item.get("type") == "order"
        and item.get("source") == "simulated"
        for item in report["evidence"]
    )


def test_investigation_returns_404_for_missing_incident(client):
    response = client.post(
        "/api/incidents/9999/investigate",
        json={"question": "What happened?"},
    )

    assert response.status_code == 404


def test_investigation_rejects_blank_question(client):
    response = client.post(
        "/api/incidents/1/investigate",
        json={"question": "   "},
    )

    assert response.status_code == 422


def test_openai_enhances_only_summary(monkeypatch):
    """OpenAI may improve the summary but cannot replace deterministic data."""
    fake_client = configure_openai(
        monkeypatch,
        content=(
            '{"summary": "AI-enhanced investigation summary"}'
        ),
    )

    report = create_deterministic_report()

    result = investigation_service.enhance_report_with_llm(report)

    assert result["summary"] == "AI-enhanced investigation summary"
    assert result["findings"] == ["Original finding"]
    assert result["hypotheses"] == ["Original hypothesis"]
    assert result["recommended_checks"] == ["Verify payment status"]
    assert result["generated_by"] == "openai"

    # The original report must not be modified.
    assert report["summary"] == "Deterministic summary"
    assert report["generated_by"] == "deterministic_fallback"

    fake_client.chat.completions.create.assert_called_once()


def test_openai_failure_preserves_deterministic_report(monkeypatch):
    """An OpenAI error returns the original deterministic report."""
    fake_client = configure_openai(
        monkeypatch,
        error=RuntimeError("Simulated API failure"),
    )

    report = create_deterministic_report()

    result = investigation_service.enhance_report_with_llm(report)

    assert result == report
    fake_client.chat.completions.create.assert_called_once()


@pytest.mark.parametrize(
    "content",
    [
        "not valid json",
        "{}",
        '{"summary": ""}',
        '{"summary": 123}',
        '{"summary": null}',
        '{"summary": "' + ("x" * 1001) + '"}',
    ],
)
def test_openai_invalid_response_preserves_report(monkeypatch, content):
    """Malformed or invalid AI output must not replace the report."""
    configure_openai(monkeypatch, content=content)

    report = create_deterministic_report()

    result = investigation_service.enhance_report_with_llm(report)

    assert result == report


def test_openai_not_configured_preserves_report(monkeypatch):
    """OpenAI is skipped when configuration is missing."""
    fake_openai = MagicMock()

    monkeypatch.setattr(
        investigation_service,
        "settings",
        MagicMock(
            llm_provider="openai",
            llm_api_key=None,
            llm_model="test-model",
        ),
    )

    monkeypatch.setattr(
        investigation_service,
        "OpenAI",
        fake_openai,
    )

    report = create_deterministic_report()

    result = investigation_service.enhance_report_with_llm(report)

    assert result == report
    fake_openai.assert_not_called()
