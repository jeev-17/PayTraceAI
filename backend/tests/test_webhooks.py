
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import OrderSource, PaymentEvent


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=test_engine)

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
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


@pytest.fixture
def webhook_payload():
    return {
        "id": f"WH-TEST-{uuid.uuid4().hex}",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2026-10-25T08:00:00Z",
        "resource": {
            "id": f"CAPTURE-{uuid.uuid4().hex}",
            "status": "COMPLETED",
        },
    }


@pytest.fixture
def valid_signature_headers():
    return {
        "Content-Type": "application/json",
        "PAYPAL-AUTH-ALGO": "SHA256withRSA",
        "PAYPAL-CERT-URL": "https://api-m.sandbox.paypal.com/cert/test",
        "PAYPAL-TRANSMISSION-ID": "test-transmission-id",
        "PAYPAL-TRANSMISSION-SIG": "test-signature",
        "PAYPAL-TRANSMISSION-TIME": "2026-10-25T08:00:00Z",
    }


def test_webhook_rejected_when_webhook_id_not_configured(
    client, webhook_payload, valid_signature_headers
):
    test_client, _ = client

    with patch.object(settings, "paypal_webhook_id", None):
        response = test_client.post(
            "/api/webhooks/paypal",
            json=webhook_payload,
            headers=valid_signature_headers,
        )

    assert response.status_code == 503


def test_webhook_rejects_invalid_signature(
    client, webhook_payload, valid_signature_headers
):
    test_client, session_factory = client

    with (
        patch.object(settings, "paypal_webhook_id", "sandbox-test-webhook"),
        patch("app.routers.webhooks.PayPalClient") as mock_class,
    ):
        mock_paypal = mock_class.return_value
        mock_paypal.verify_webhook_signature.return_value = False

        response = test_client.post(
            "/api/webhooks/paypal",
            json=webhook_payload,
            headers=valid_signature_headers,
        )

        mock_paypal.verify_webhook_signature.assert_called_once()
        mock_paypal.close.assert_called_once()

    assert response.status_code == 400

    with session_factory() as db:
        assert db.query(PaymentEvent).count() == 0


def test_verified_webhook_is_persisted(
    client, webhook_payload, valid_signature_headers
):
    test_client, session_factory = client

    with (
        patch.object(settings, "paypal_webhook_id", "sandbox-test-webhook"),
        patch("app.routers.webhooks.PayPalClient") as mock_class,
    ):
        mock_paypal = mock_class.return_value
        mock_paypal.verify_webhook_signature.return_value = True

        response = test_client.post(
            "/api/webhooks/paypal",
            json=webhook_payload,
            headers=valid_signature_headers,
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received"

    with session_factory() as db:
        event = db.query(PaymentEvent).one()
        assert event.paypal_event_id == webhook_payload["id"]
        assert event.event_type == webhook_payload["event_type"]
        assert event.source == OrderSource.PAYPAL_SANDBOX
        assert event.verification_status.value == "verified"
        assert event.is_duplicate_delivery is False


def test_duplicate_webhook_is_not_stored_twice(
    client, webhook_payload, valid_signature_headers
):
    test_client, session_factory = client

    with (
        patch.object(settings, "paypal_webhook_id", "sandbox-test-webhook"),
        patch("app.routers.webhooks.PayPalClient") as mock_class,
    ):
        mock_paypal = mock_class.return_value
        mock_paypal.verify_webhook_signature.return_value = True

        first = test_client.post(
            "/api/webhooks/paypal",
            json=webhook_payload,
            headers=valid_signature_headers,
        )
        second = test_client.post(
            "/api/webhooks/paypal",
            json=webhook_payload,
            headers=valid_signature_headers,
        )

    assert first.status_code == 200, first.text
    assert first.json()["status"] == "received"
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate"

    with session_factory() as db:
        assert db.query(PaymentEvent).count() == 1


def test_webhook_verification_service_failure_is_not_accepted(
    client, webhook_payload, valid_signature_headers
):
    from app.services.paypal_client import PayPalError

    test_client, session_factory = client

    with (
        patch.object(settings, "paypal_webhook_id", "sandbox-test-webhook"),
        patch("app.routers.webhooks.PayPalClient") as mock_class,
    ):
        mock_paypal = mock_class.return_value
        mock_paypal.verify_webhook_signature.side_effect = PayPalError(
            "Verification service unavailable."
        )

        response = test_client.post(
            "/api/webhooks/paypal",
            json=webhook_payload,
            headers=valid_signature_headers,
        )

    assert response.status_code == 503

    with session_factory() as db:
        assert db.query(PaymentEvent).count() == 0
