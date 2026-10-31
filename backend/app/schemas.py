from datetime import datetime
from decimal import Decimal
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    IncidentStatus,
    OrderSource,
    OrderStatus,
    VerificationStatus,
)


class HealthResponse(BaseModel):
    status: str
    config_present: dict[str, bool]


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paypal_order_id: str
    amount: Decimal
    currency: str
    status: OrderStatus
    source: OrderSource
    created_at: datetime
    updated_at: datetime
    last_verified_at: datetime | None
    last_verified_status: str | None
    approval_url: str | None = None

class PaymentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paypal_event_id: str
    order_id: int | None
    paypal_order_ref: str | None
    event_type: str
    resource_id: str | None
    source: OrderSource
    delivery_received_at: datetime
    event_created_at: datetime | None
    verification_status: VerificationStatus
    is_duplicate_delivery: bool
    payload_json: dict[str, object]
    processed_at: datetime | None


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: str
    severity: str
    status: IncidentStatus
    order_id: int | None
    evidence_event_ids: list[int]
    description: str
    created_at: datetime
    resolved_at: datetime | None
    resolution_reason: str | None
    dedup_key: str


class AuditRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    details_json: dict[str, object]


class CreateOrderRequest(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)


class CaptureRequest(BaseModel):
    confirm: bool = True


class VerifyRequest(BaseModel):
    pass


class ResolveIncidentRequest(BaseModel):
    resolution_reason: str = Field(min_length=1, max_length=2000)


class InvestigateIncidentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class SimulationRunRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=128)

class InvestigationResponse(BaseModel):
    incident_id: int
    question: str
    summary: str
    findings: list[str]
    hypotheses: list[str]
    recommended_checks: list[str]
    evidence: list[dict[str, Any]]
    limitations: list[str]
    generated_by: str
