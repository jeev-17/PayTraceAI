
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Incident,
    IncidentStatus,
    Order,
    OrderStatus,
    PaymentEvent,
    VerificationStatus,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def detect_incidents(db: Session) -> list[Incident]:
    """Detect incidents from stored orders and verified payment events.

    This function records findings only. It never changes payment status
    or initiates PayPal operations.
    """
    now = utc_now()
    detected: list[Incident] = []

    # Rule 1: orders that remain pending beyond the configured threshold.
    cutoff = now - timedelta(minutes=settings.pending_threshold_minutes)

    pending_orders = (
        db.query(Order)
        .filter(Order.status == OrderStatus.PENDING)
        .all()
    )

    for order in pending_orders:
        created_at = order.created_at
        if created_at is None:
            continue

        # SQLite may return naive datetimes even when timezone=True.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        if created_at > cutoff:
            continue

        dedup_key = f"pending-timeout:order:{order.id}"

        incident = _create_if_new(
            db=db,
            dedup_key=dedup_key,
            rule_id="PENDING_ORDER_TIMEOUT",
            severity="medium",
            order_id=order.id,
            evidence_event_ids=[],
            description=(
                f"Order {order.paypal_order_id} has remained pending "
                f"beyond {settings.pending_threshold_minutes} minutes. "
                "Verify its current state with PayPal before taking action."
            ),
        )
        if incident is not None:
            detected.append(incident)

    # Rule 2: a verified completed capture conflicts with a non-completed
    # local order. This is a reconciliation finding, not proof of fraud.
    completed_capture_events = (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.verification_status == VerificationStatus.VERIFIED,
            PaymentEvent.event_type == "PAYMENT.CAPTURE.COMPLETED",
        )
        .all()
    )

    for event in completed_capture_events:
        if event.order_id is None:
            continue

        order = db.query(Order).filter(Order.id == event.order_id).first()
        if order is None or order.status == OrderStatus.COMPLETED:
            continue

        dedup_key = f"capture-status-mismatch:event:{event.id}"

        incident = _create_if_new(
            db=db,
            dedup_key=dedup_key,
            rule_id="CAPTURE_STATUS_MISMATCH",
            severity="high",
            order_id=order.id,
            evidence_event_ids=[event.id],
            description=(
                f"Verified capture-completed event {event.paypal_event_id} "
                f"is associated with order {order.paypal_order_id}, but the "
                f"local order status is '{order.status.value}'. "
                "Retrieve the current PayPal order/capture state before "
                "reconciling local records."
            ),
        )
        if incident is not None:
            detected.append(incident)

    # Rule 3: verified events that refer to an order we cannot match.
    unmatched_events = (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.verification_status == VerificationStatus.VERIFIED,
            PaymentEvent.paypal_order_ref.is_not(None),
            PaymentEvent.order_id.is_(None),
        )
        .all()
    )

    for event in unmatched_events:
        dedup_key = f"unmatched-event:event:{event.id}"

        incident = _create_if_new(
            db=db,
            dedup_key=dedup_key,
            rule_id="UNMATCHED_PAYMENT_EVENT",
            severity="medium",
            order_id=None,
            evidence_event_ids=[event.id],
            description=(
                f"Verified event {event.paypal_event_id} references PayPal "
                f"order {event.paypal_order_ref}, which could not be matched "
                "to a locally stored order. Investigate the reference before "
                "making any payment-state changes."
            ),
        )
        if incident is not None:
            detected.append(incident)

    return detected


def _create_if_new(
    db: Session,
    *,
    dedup_key: str,
    rule_id: str,
    severity: str,
    order_id: int | None,
    evidence_event_ids: list[int],
    description: str,
) -> Incident | None:
    existing = (
        db.query(Incident)
        .filter(Incident.dedup_key == dedup_key)
        .first()
    )

    if existing is not None:
        return None

    incident = Incident(
        dedup_key=dedup_key,
        rule_id=rule_id,
        severity=severity,
        status=IncidentStatus.OPEN,
        order_id=order_id,
        evidence_event_ids=evidence_event_ids,
        description=description,
    )

    db.add(incident)
    db.flush()
    return incident
