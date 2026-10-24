from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, normalize_origin


def test_cors_middleware_uses_configured_frontend_origin() -> None:
    origin = normalize_origin(settings.frontend_origin)

    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Origin": origin})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_origin_normalizes_service_host_without_scheme() -> None:
    from app.main import normalize_origin

    assert normalize_origin("paytrace-ui.onrender.com") == (
        "https://paytrace-ui.onrender.com"
    )
    assert normalize_origin("https://paytrace-ui.onrender.com/") == (
        "https://paytrace-ui.onrender.com"
    )
