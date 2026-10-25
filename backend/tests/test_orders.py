
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.paypal_client import PayPalError


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
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def test_create_order_success(client):
    paypal_id = f"SANDBOX-TEST-{uuid.uuid4().hex}"
    idempotency_key = f"test-create-order-{uuid.uuid4().hex}"

    with patch("app.routers.orders.PayPalClient") as mock_class:
        mock_paypal = mock_class.return_value
        mock_paypal.create_order.return_value = {
            "id": paypal_id,
            "status": "CREATED",
        }

        response = client.post(
            "/api/orders",
            json={"amount": "12.50", "currency": "USD"},
            headers={"Idempotency-Key": idempotency_key},
        )

        assert response.status_code == 201, response.text

        data = response.json()
        assert data["paypal_order_id"] == paypal_id
        assert data["amount"] == "12.50"
        assert data["currency"] == "USD"
        assert data["status"] == "created"
        assert data["source"] == "paypal_sandbox"

        mock_paypal.create_order.assert_called_once()
        mock_paypal.close.assert_called_once()


def test_create_order_rejects_unsupported_currency(client):
    with patch("app.routers.orders.PayPalClient") as mock_class:
        response = client.post(
            "/api/orders",
            json={"amount": "12.50", "currency": "EUR"},
            headers={
                "Idempotency-Key": f"test-invalid-{uuid.uuid4().hex}"
            },
        )

        assert response.status_code == 422
        mock_class.assert_not_called()


def test_create_order_handles_paypal_error(client):
    idempotency_key = f"test-paypal-error-{uuid.uuid4().hex}"

    with patch("app.routers.orders.PayPalClient") as mock_class:
        mock_paypal = mock_class.return_value
        mock_paypal.create_order.side_effect = PayPalError(
            "PayPal Sandbox could not create the order."
        )

        response = client.post(
            "/api/orders",
            json={"amount": "12.50", "currency": "USD"},
            headers={"Idempotency-Key": idempotency_key},
        )

        assert response.status_code == 502
        assert "Sandbox" in response.json()["error"]["message"]
        mock_paypal.close.assert_called_once()

def test_same_idempotency_key_returns_existing_order(client):
    import uuid
    from unittest.mock import patch

    idempotency_key = f"test-idempotency-{uuid.uuid4().hex}"
    headers = {"Idempotency-Key": idempotency_key}
    payload = {"amount": "12.50", "currency": "USD"}

    with patch("app.routers.orders.PayPalClient") as mock_class:
        mock_paypal = mock_class.return_value
        mock_paypal.create_order.return_value = {
            "id": f"SANDBOX-TEST-{uuid.uuid4().hex}",
            "status": "CREATED",
        }

        first_response = client.post(
            "/api/orders", json=payload, headers=headers
        )
        second_response = client.post(
            "/api/orders", json=payload, headers=headers
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 201
        assert (
            first_response.json()["paypal_order_id"]
            == second_response.json()["paypal_order_id"]
        )
        assert mock_paypal.create_order.call_count == 1


def test_same_idempotency_key_with_different_amount_returns_409(client):
    import uuid
    from unittest.mock import patch

    idempotency_key = f"test-idempotency-{uuid.uuid4().hex}"
    headers = {"Idempotency-Key": idempotency_key}

    with patch("app.routers.orders.PayPalClient") as mock_class:
        mock_paypal = mock_class.return_value
        mock_paypal.create_order.return_value = {
            "id": f"SANDBOX-TEST-{uuid.uuid4().hex}",
            "status": "CREATED",
        }

        first_response = client.post(
            "/api/orders",
            json={"amount": "12.50", "currency": "USD"},
            headers=headers,
        )
        second_response = client.post(
            "/api/orders",
            json={"amount": "15.00", "currency": "USD"},
            headers=headers,
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 409
        assert mock_paypal.create_order.call_count == 1
