
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditRecord, Order, OrderSource


@pytest.fixture
def client_and_db():
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
        yield client, TestingSessionLocal

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_run_simulation_endpoint_creates_simulated_order(client_and_db):
    client, SessionLocal = client_and_db

    response = client.post(
        "/api/simulations/run",
        json={"scenario_id": "pending_timeout"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["scenario_id"] == "pending_timeout"
    assert result["source"] == "simulated"
    assert result["status"] == "pending"

    db = SessionLocal()
    try:
        order = db.query(Order).filter_by(id=result["order_id"]).one()
        assert order.source == OrderSource.SIMULATED
        assert db.query(AuditRecord).count() == 1
    finally:
        db.close()


def test_unknown_simulation_scenario_returns_422(client_and_db):
    client, SessionLocal = client_and_db

    response = client.post(
        "/api/simulations/run",
        json={"scenario_id": "not_a_real_scenario"},
    )

    assert response.status_code == 422

    db = SessionLocal()
    try:
        assert db.query(Order).count() == 0
        assert db.query(AuditRecord).count() == 0
    finally:
        db.close()


def test_missing_scenario_id_returns_422(client_and_db):
    client, _ = client_and_db

    response = client.post("/api/simulations/run", json={})

    assert response.status_code == 422

def test_simulation_then_incident_scan_detects_pending_timeout(client_and_db):
    client, SessionLocal = client_and_db

    simulation = client.post(
        "/api/simulations/run",
        json={"scenario_id": "pending_timeout"},
    )

    assert simulation.status_code == 200
    simulated_order_id = simulation.json()["order_id"]

    scan = client.post("/api/incidents/scan")

    assert scan.status_code == 200
    incidents = scan.json()

    matching = [
        incident
        for incident in incidents
        if incident["rule_id"] == "PENDING_ORDER_TIMEOUT"
        and incident["order_id"] == simulated_order_id
    ]
    assert len(matching) == 1

    listed = client.get("/api/incidents")
    assert listed.status_code == 200
    assert any(
        incident["id"] == matching[0]["id"]
        for incident in listed.json()
    )

    db = SessionLocal()
    try:
        from app.models import Order, OrderSource

        order = db.query(Order).filter_by(id=simulated_order_id).one()
        assert order.source == OrderSource.SIMULATED
    finally:
        db.close()
