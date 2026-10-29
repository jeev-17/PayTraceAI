
from datetime import timedelta, timezone

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
from app.models import (
    Incident,
    IncidentStatus,
    Order,
    OrderStatus,
    PaymentEvent,
    VerificationStatus,
    utc_now,
)


def _create_if_new(
    db: Session,
    dedup_key: str,
    rule_id: str,
    severity: str,
    order_id: int | None,
    evidence_event_ids: list[int],
    description: str,
) -> Incident | None:
    """Create an incident only if an incident with this key does not exist."""

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


def detect_incidents(db: Session) -> list[Incident]:
    """Detect incidents from stored orders and verified payment events.

    This function records findings only. It never changes payment status
    or initiates PayPal operations.
    """

    now = utc_now()
    detected: list[Incident] = []

    # Rule 1: orders that remain pending beyond the configured threshold.
    cutoff = now - timedelta(
        minutes=settings.pending_threshold_minutes
    )

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

        # Link stored events explicitly associated with this order.
        related_events = (
            db.query(PaymentEvent)
            .filter(PaymentEvent.order_id == order.id)
            .order_by(PaymentEvent.delivery_received_at.asc())
            .all()
        )

        evidence_event_ids = [
            event.id for event in related_events
        ]

        dedup_key = f"pending-timeout:order:{order.id}"

        incident = _create_if_new(
            db=db,
            dedup_key=dedup_key,
            rule_id="PENDING_ORDER_TIMEOUT",
            severity="medium",
            order_id=order.id,
            evidence_event_ids=evidence_event_ids,
            description=(
                f"Order {order.paypal_order_id or order.id} "
                "has remained pending beyond the configured "
                "threshold. Verify the current payment state "
                "with PayPal before taking action."
            ),
        )

        if incident is not None:
            detected.append(incident)

    # Rule 2: verified capture-completed events conflict with local status.
    completed_capture_events = (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.event_type == "PAYMENT.CAPTURE.COMPLETED",
            PaymentEvent.verification_status
            == VerificationStatus.VERIFIED,
            PaymentEvent.order_id.isnot(None),
        )
        .all()
    )

    for event in completed_capture_events:
        order = (
            db.query(Order)
            .filter(Order.id == event.order_id)
            .first()
        )

        if order is None:
            continue

        if order.status == OrderStatus.COMPLETED:
            continue

        dedup_key = (
            f"capture-status-mismatch:"
            f"event:{event.id}:order:{order.id}"
        )

        incident = _create_if_new(
            db=db,
            dedup_key=dedup_key,
            rule_id="CAPTURE_STATUS_MISMATCH",
            severity="high",
            order_id=order.id,
            evidence_event_ids=[event.id],
            description=(
                f"Verified capture-completed event {event.id} "
                f"is linked to order {order.paypal_order_id or order.id}, "
                f"but the local order status is '{order.status.value}'. "
                "Verify the current payment state with PayPal "
                "before reconciling the order."
            ),
        )

        if incident is not None:
            detected.append(incident)

    # Rule 3: verified payment events that cannot be linked to a local order.
    unmatched_events = (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.verification_status
            == VerificationStatus.VERIFIED,
            PaymentEvent.paypal_order_ref.isnot(None),
            PaymentEvent.order_id.is_(None),
        )
        .all()
    )

    for event in unmatched_events:
        dedup_key = f"unmatched-payment-event:event:{event.id}"

        incident = _create_if_new(
            db=db,
            dedup_key=dedup_key,
            rule_id="UNMATCHED_PAYMENT_EVENT",
            severity="medium",
            order_id=None,
            evidence_event_ids=[event.id],
            description=(
                f"Verified payment event {event.id} references "
                f"PayPal order {event.paypal_order_ref}, but it is "
                "not linked to a local order. Check the order mapping "
                "and stored event details."
            ),
        )

        if incident is not None:
            detected.append(incident)

    return detected
