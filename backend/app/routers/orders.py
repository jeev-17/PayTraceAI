
import hashlib
import logging
import re
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditRecord, Order, OrderSource, OrderStatus
from app.schemas import CreateOrderRequest, OrderResponse
from app.services.paypal_client import PayPalClient, PayPalError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])
ALLOWED_CURRENCIES = {"USD"}


def make_paypal_request_id(idempotency_key: str) -> str:
    digest = hashlib.sha256(
        idempotency_key.encode("utf-8")
    ).hexdigest()
    return f"pt-{digest[:32]}"


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    request: CreateOrderRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
    ),
    db: Session = Depends(get_db),
) -> OrderResponse:
    currency = request.currency.upper()

    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise HTTPException(
            status_code=422,
            detail="Currency must be a three-letter currency code.",
        )

    if currency not in ALLOWED_CURRENCIES:
        raise HTTPException(
            status_code=422,
            detail="Only USD is currently supported.",
        )

    amount = Decimal(request.amount).quantize(Decimal("0.01"))

    # Repeated requests with the same key must describe the same order.
    existing = (
        db.query(Order)
        .filter(Order.idempotency_key == idempotency_key)
        .first()
    )

    if existing:
        if existing.amount != amount or existing.currency != currency:
            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used with different order details.",
            )
        return OrderResponse.model_validate(existing)

    paypal_request_id = make_paypal_request_id(idempotency_key)
    client = PayPalClient()

    try:
        paypal_response = client.create_order(
            amount=f"{amount:.2f}",
            currency=currency,
            reference=paypal_request_id,
            request_id=paypal_request_id,
        )
    except PayPalError as exc:
        logger.warning(
            "PayPal order creation error; uncertain=%s status_code=%s debug_id=%s",
            exc.uncertain,
            exc.status_code,
            exc.debug_id,
        )

        if exc.uncertain:
            raise HTTPException(
                status_code=502,
                detail=(
                    "PayPal order creation outcome is uncertain. "
                    "Do not create a new order. Retry only with the same "
                    "Idempotency-Key or verify the order with PayPal."
                ),
            ) from exc

        raise HTTPException(
            status_code=502,
            detail="PayPal Sandbox could not create the order.",
        ) from exc
    finally:
        client.close()

    paypal_order_id = paypal_response.get("id")
    paypal_status = paypal_response.get("status")
    approval_url = next(
        (
            link.get("href")
            for link in paypal_response.get("links", [])
            if link.get("rel") == "approve"
        ),
        None,
    )

    if not isinstance(paypal_order_id, str) or not paypal_order_id:
        raise HTTPException(
            status_code=502,
            detail="PayPal returned an invalid order response.",
        )

    status_map = {
        "CREATED": OrderStatus.CREATED,
        "SAVED": OrderStatus.CREATED,
        "APPROVED": OrderStatus.APPROVED,
        "PAYER_ACTION_REQUIRED": OrderStatus.PENDING,
    }

    if paypal_status not in status_map:
        logger.warning(
            "Unexpected PayPal create-order status: %s",
            paypal_status,
        )
        raise HTTPException(
            status_code=502,
            detail="PayPal returned an unexpected order status.",
        )

    # Validate the returned purchase-unit amount when present.
    purchase_units = paypal_response.get("purchase_units")
    if isinstance(purchase_units, list) and purchase_units:
        returned_amount = purchase_units[0].get("amount")
        if isinstance(returned_amount, dict):
            returned_currency = returned_amount.get("currency_code")
            returned_value = returned_amount.get("value")

            if (
                returned_currency != currency
                or returned_value != f"{amount:.2f}"
            ):
                logger.error(
                    "PayPal response amount/currency mismatch; order_id=%s",
                    paypal_order_id,
                )
                raise HTTPException(
                    status_code=502,
                    detail="PayPal returned order details that did not match the request.",
                )

    order = Order(
        paypal_order_id=paypal_order_id,
        amount=amount,
        currency=currency,
        status=status_map[paypal_status],
        source=OrderSource.PAYPAL_SANDBOX,
        idempotency_key=idempotency_key,
    )

    try:
        db.add(order)
        db.flush()

        db.add(
            AuditRecord(
                actor="system",
                action="paypal_sandbox_order_created",
                entity_type="order",
                entity_id=str(order.id),
                details_json={
                    "paypal_order_id": paypal_order_id,
                    "amount": f"{amount:.2f}",
                    "currency": currency,
                    "status": order.status.value,
                },
            )
        )

        db.commit()
        db.refresh(order)
    except IntegrityError as exc:
        db.rollback()

        # Another request may have completed with the same key concurrently.
        existing = (
            db.query(Order)
            .filter(Order.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            if existing.amount == amount and existing.currency == currency:
                return OrderResponse.model_validate(existing)

            raise HTTPException(
                status_code=409,
                detail="Idempotency-Key was already used with different order details.",
            ) from exc

        logger.exception("Database integrity error while saving PayPal order")
        raise HTTPException(
            status_code=409,
            detail="The order could not be saved because of a data conflict.",
        ) from exc
    except Exception:
        db.rollback()
        raise
    order_response = OrderResponse.model_validate(order)
    return order_response.model_copy(
        update={"approval_url": approval_url}
    )