
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentEvent, OrderSource

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events(
    source: str | None = None,
    event_type: str | None = None,
    order_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """List stored payment events without exposing raw payloads."""

    query = db.query(PaymentEvent)

    if source is not None:
        allowed_sources = {item.value for item in OrderSource}
        if source not in allowed_sources:
            raise HTTPException(
                status_code=400,
                detail="Unsupported event source.",
            )
        query = query.filter(PaymentEvent.source == source)

    if event_type:
        query = query.filter(PaymentEvent.event_type == event_type)

    if order_id is not None:
        query = query.filter(PaymentEvent.order_id == order_id)

    total = query.count()

    events = (
        query.order_by(PaymentEvent.delivery_received_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": event.id,
                "paypal_event_id": event.paypal_event_id,
                "order_id": event.order_id,
                "paypal_order_ref": event.paypal_order_ref,
                "event_type": event.event_type,
                "resource_id": event.resource_id,
                "source": (
                    event.source.value
                    if hasattr(event.source, "value")
                    else str(event.source)
                ),
                "delivery_received_at": event.delivery_received_at,
                "event_created_at": event.event_created_at,
                "verification_status": (
                    event.verification_status.value
                    if hasattr(event.verification_status, "value")
                    else str(event.verification_status)
                ),
                "is_duplicate_delivery": event.is_duplicate_delivery,
                "processed_at": event.processed_at,
            }
            for event in events
        ],
    }