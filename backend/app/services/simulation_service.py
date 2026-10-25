
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AuditRecord,
    Order,
    OrderSource,
    OrderStatus,
    utc_now,
)


def run_simulation(db: Session, scenario_id: str) -> dict[str, object]:
    """Create isolated simulated data without making any PayPal API calls."""
    scenario_id = scenario_id.strip().lower()

    if scenario_id != "pending_timeout":
        raise ValueError(
            "Unsupported scenario. Available scenario: pending_timeout."
        )

    now = datetime.now(timezone.utc)
    unique_id = uuid4().hex[:12]
    simulated_order_id = f"SIM-ORDER-{unique_id}"

    order = Order(
        paypal_order_id=simulated_order_id,
        amount=Decimal("25.00"),
        currency="USD",
        status=OrderStatus.PENDING,
        source=OrderSource.SIMULATED,
        idempotency_key=None,
        created_at=now - timedelta(
            minutes=settings.pending_threshold_minutes + 5
        ),
        updated_at=now,
    )

    try:
        db.add(order)
        db.flush()

        audit = AuditRecord(
            actor="simulation",
            action="SIMULATION_RUN",
            entity_type="order",
            entity_id=simulated_order_id,
            details_json={
                "scenario_id": scenario_id,
                "source": "simulated",
                "note": "Synthetic test data; no PayPal payment operation was performed.",
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(order)

        return {
            "scenario_id": scenario_id,
            "source": "simulated",
            "order_id": order.id,
            "simulated_order_ref": order.paypal_order_id,
            "status": order.status.value,
            "message": (
                "Simulated pending order created. Run the incident scan "
                "to detect the pending-timeout condition."
            ),
        }

    except Exception:
        db.rollback()
        raise
