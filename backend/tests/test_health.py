from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_status_and_boolean_config_presence() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["config_present"]["paypal_client_id"] is False
    assert all(isinstance(value, bool) for value in body["config_present"].values())
