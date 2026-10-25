
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuditRecord, Order, OrderSource, OrderStatus
from app.services.simulation_service import run_simulation


@pytest.fixture
def db():
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
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_pending_timeout_simulation_creates_simulated_order(db):
    result = run_simulation(db, "pending_timeout")

    order = db.query(Order).filter_by(id=result["order_id"]).one()

    assert result["scenario_id"] == "pending_timeout"
    assert result["source"] == "simulated"
    assert result["status"] == "pending"
    assert order.source == OrderSource.SIMULATED
    assert order.status == OrderStatus.PENDING
    assert order.amount == Decimal("25.00")
    assert order.paypal_order_id.startswith("SIM-ORDER-")


def test_simulation_writes_audit_record(db):
    result = run_simulation(db, "pending_timeout")

    audit = (
        db.query(AuditRecord)
        .filter_by(entity_id=result["simulated_order_ref"])
        .one()
    )

    assert audit.action == "SIMULATION_RUN"
    assert audit.actor == "simulation"
    assert audit.details_json["source"] == "simulated"


def test_unsupported_scenario_is_rejected(db):
    with pytest.raises(ValueError, match="Unsupported scenario"):
        run_simulation(db, "unknown_scenario")

    assert db.query(Order).count() == 0
    assert db.query(AuditRecord).count() == 0


def test_repeated_simulations_create_separate_records(db):
    first = run_simulation(db, "pending_timeout")
    second = run_simulation(db, "pending_timeout")

    assert first["simulated_order_ref"] != second["simulated_order_ref"]
    assert db.query(Order).count() == 2
    assert db.query(Order).filter_by(source=OrderSource.SIMULATED).count() == 2
