import logging
import uuid
from datetime import datetime
from typing import Any
from unittest.mock import patch

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
        logger.error("PayPal webhook verification is not configured.")

        raise HTTPException(
            status_code=503,
            detail="PayPal webhook verification is not configured.",
        )

    try:
        payload = await request.json()
    except Exception:
        logger.warning("PayPal webhook rejected: invalid JSON payload.")

        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload.",
        )

    if not isinstance(payload, dict):
        logger.warning("PayPal webhook rejected: expected a JSON object.")

        raise HTTPException(
            status_code=400,
            detail="Expected a JSON object.",
        )

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
        logger.warning(
            "PayPal webhook rejected: required event fields are missing."
        )

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
        logger.exception(
            "PayPal webhook signature verification service failed."
        )

        raise HTTPException(
            status_code=503,
            detail="Webhook verification service is unavailable.",
        )

    finally:
        client.close()

    if not verified:
        logger.warning(
            "PayPal webhook rejected: signature verification returned false. "
            "event_id=%s event_type=%s",
            event_id,
            event_type,
        )

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

    # For CHECKOUT.ORDER.* events, the resource itself is the order,
    # so its id is the PayPal order ID. (For capture events, resource.id
    # is the capture ID, so this fallback must not apply to them.)
    if (
        paypal_order_ref is None
        and event_type.startswith("CHECKOUT.ORDER.")
        and resource_id
    ):
        paypal_order_ref = resource_id

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
        logger.info(
            "Duplicate PayPal webhook delivery ignored. event_id=%s",
            event_id,
        )

        return {
            "status": "duplicate",
            "event_id": event_id,
        }

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

        duplicate = (
            db.query(PaymentEvent)
            .filter(
                PaymentEvent.source == OrderSource.PAYPAL_SANDBOX,
                PaymentEvent.paypal_event_id == event_id,
            )
            .first()
        )

        if duplicate:
            logger.info(
                "Concurrent duplicate PayPal webhook ignored. event_id=%s",
                event_id,
            )

            return {
                "status": "duplicate",
                "event_id": event_id,
            }

        logger.exception(
            "Could not persist PayPal webhook event."
        )

        raise HTTPException(
            status_code=500,
            detail="Could not persist webhook event.",
        )

    except Exception:
        db.rollback()

        logger.exception(
            "Could not persist verified PayPal webhook."
        )

        raise HTTPException(
            status_code=500,
            detail="Could not persist webhook event.",
        )

    logger.info(
        "PayPal webhook received and stored successfully. "
        "event_id=%s event_type=%s",
        event_id,
        event_type,
    )

    return {
        "status": "received",
        "event_id": event_id,
    }
def _make_test_order(session_factory, paypal_order_id):
    from decimal import Decimal

    from app.models import Order, OrderStatus

    with session_factory() as db:
        order = Order(
            paypal_order_id=paypal_order_id,
            amount=Decimal("1.00"),
            currency="USD",
            status=OrderStatus.CREATED,
            source=OrderSource.PAYPAL_SANDBOX,
            idempotency_key=f"test-{uuid.uuid4().hex}",
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order.id


def test_order_approved_event_links_to_order_by_resource_id(
    client, valid_signature_headers
):
    test_client, session_factory = client
    order_pk = _make_test_order(session_factory, "ORDER-TEST-APPROVED")

    payload = {
        "id": f"WH-TEST-{uuid.uuid4().hex}",
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "create_time": "2026-10-25T08:00:00Z",
        "resource": {"id": "ORDER-TEST-APPROVED", "status": "APPROVED"},
    }

    with (
        patch.object(settings, "paypal_webhook_id", "sandbox-test-webhook"),
        patch("app.routers.webhooks.PayPalClient") as mock_class,
    ):
        mock_class.return_value.verify_webhook_signature.return_value = True

        response = test_client.post(
            "/api/webhooks/paypal",
            json=payload,
            headers=valid_signature_headers,
        )

    assert response.status_code == 200

    with session_factory() as db:
        event = (
            db.query(PaymentEvent)
            .filter(PaymentEvent.paypal_event_id == payload["id"])
            .one()
        )
        assert event.order_id == order_pk
        assert event.paypal_order_ref == "ORDER-TEST-APPROVED"


def test_capture_event_resource_id_is_not_used_as_order_id(
    client, valid_signature_headers
):
    test_client, session_factory = client
    _make_test_order(session_factory, "ORDER-TEST-CAPTURE-GUARD")

    payload = {
        "id": f"WH-TEST-{uuid.uuid4().hex}",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2026-10-25T08:00:00Z",
        # For capture events this is the capture ID, never the order ID.
        "resource": {"id": "ORDER-TEST-CAPTURE-GUARD", "status": "COMPLETED"},
    }

    with (
        patch.object(settings, "paypal_webhook_id", "sandbox-test-webhook"),
        patch("app.routers.webhooks.PayPalClient") as mock_class,
    ):
        mock_class.return_value.verify_webhook_signature.return_value = True

        response = test_client.post(
            "/api/webhooks/paypal",
            json=payload,
            headers=valid_signature_headers,
        )

    assert response.status_code == 200

    with session_factory() as db:
        event = (
            db.query(PaymentEvent)
            .filter(PaymentEvent.paypal_event_id == payload["id"])
            .one()
        )
        assert event.order_id is None
        assert event.paypal_order_ref is None