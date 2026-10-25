
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    Order,
    OrderSource,
    PaymentEvent,
    VerificationStatus,
    utc_now,
)
from app.services.paypal_client import PayPalClient, PayPalError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def parse_event_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/paypal")
async def receive_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not settings.paypal_webhook_id:
        raise HTTPException(
            status_code=503,
            detail="PayPal webhook verification is not configured.",
        )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")

    event_id = payload.get("id")
    event_type = payload.get("event_type")
    resource = payload.get("resource")

    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(event_type, str)
        or not event_type
        or not isinstance(resource, dict)
    ):
        raise HTTPException(
            status_code=400,
            detail="Webhook payload is missing required event fields.",
        )

    headers = dict(request.headers)
    client = PayPalClient()

    try:
        verified = client.verify_webhook_signature(
            headers=headers,
            webhook_id=settings.paypal_webhook_id,
            webhook_event=payload,
        )
    except PayPalError:
        logger.exception("PayPal webhook signature verification failed")
        raise HTTPException(
            status_code=503,
            detail="Webhook verification service is unavailable.",
        )
    finally:
        client.close()

    if not verified:
        raise HTTPException(
            status_code=400,
            detail="PayPal webhook signature could not be verified.",
        )

    resource_id = resource.get("id")
    supplementary = resource.get("supplementary_data")
    related_ids = (
        supplementary.get("related_ids", {})
        if isinstance(supplementary, dict)
        else {}
    )
    paypal_order_ref = (
        related_ids.get("order_id")
        if isinstance(related_ids, dict)
        else None
    )

    if not isinstance(paypal_order_ref, str):
        paypal_order_ref = None
    if not isinstance(resource_id, str):
        resource_id = None

    order = None
    if paypal_order_ref:
        order = (
            db.query(Order)
            .filter(Order.paypal_order_id == paypal_order_ref)
            .first()
        )

    existing = (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.source == OrderSource.PAYPAL_SANDBOX,
            PaymentEvent.paypal_event_id == event_id,
        )
        .first()
    )

    if existing:
        return {"status": "duplicate", "event_id": event_id}

    event = PaymentEvent(
        paypal_event_id=event_id,
        order_id=order.id if order else None,
        paypal_order_ref=paypal_order_ref,
        event_type=event_type,
        resource_id=resource_id,
        source=OrderSource.PAYPAL_SANDBOX,
        event_created_at=parse_event_time(payload.get("create_time")),
        verification_status=VerificationStatus.VERIFIED,
        is_duplicate_delivery=False,
        payload_json=payload,
        processed_at=utc_now(),
    )

    try:
        db.add(event)
        db.commit()
    except IntegrityError:
        db.rollback()
        # Another request may have persisted the same event concurrently.
        duplicate = (
            db.query(PaymentEvent)
            .filter(
                PaymentEvent.source == OrderSource.PAYPAL_SANDBOX,
                PaymentEvent.paypal_event_id == event_id,
            )
            .first()
        )
        if duplicate:
            return {"status": "duplicate", "event_id": event_id}
        raise HTTPException(
            status_code=500,
            detail="Could not persist webhook event.",
        )
    except Exception:
        db.rollback()
        logger.exception("Could not persist verified PayPal webhook")
        raise HTTPException(
            status_code=500,
            detail="Could not persist webhook event.",
        )

    return {"status": "received", "event_id": event_id}
