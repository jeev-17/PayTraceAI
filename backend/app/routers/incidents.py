from datetime import timezone
from app.schemas import InvestigationResponse, InvestigateIncidentRequest
from app.services.investigation_service import investigate_incident
from app.models import AuditRecord, Incident, IncidentStatus, utc_now
from app.schemas import IncidentResponse, ResolveIncidentRequest
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Incident, IncidentStatus
from app.schemas import IncidentResponse
from app.services.incident_engine import detect_incidents

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.post("/scan", response_model=list[IncidentResponse])
def scan_incidents(db: Session = Depends(get_db)):
    """Detect new incidents and return the incidents created by this scan."""
    try:
        incidents = detect_incidents(db)
        db.commit()

        for incident in incidents:
            db.refresh(incident)

        return incidents
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Incident scan failed. No changes from this scan were committed.",
        )


@router.get("", response_model=list[IncidentResponse])
def list_incidents(
    status: IncidentStatus | None = None,
    db: Session = Depends(get_db),
):
    """List incidents, optionally filtered by status."""
    query = db.query(Incident)

    if status is not None:
        query = query.filter(Incident.status == status)

    return query.order_by(Incident.created_at.desc()).all()

@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(
    incident_id: int,
    request: ResolveIncidentRequest,
    db: Session = Depends(get_db),
):
    reason = request.resolution_reason.strip()

    if not reason:
        raise HTTPException(
            status_code=422,
            detail="Resolution reason cannot be blank.",
        )

    incident = (
        db.query(Incident)
        .filter(Incident.id == incident_id)
        .first()
    )

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found.",
        )

    if incident.status == IncidentStatus.RESOLVED:
        raise HTTPException(
            status_code=409,
            detail="Incident is already resolved.",
        )

    try:
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = utc_now()
        incident.resolution_reason = reason

        audit = AuditRecord(
            actor="developer",
            action="INCIDENT_RESOLVED",
            entity_type="incident",
            entity_id=str(incident.id),
            details_json={
                "resolution_reason": reason,
                "rule_id": incident.rule_id,
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(incident)

        return incident

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to resolve incident.",
        )
@router.post(
    "/{incident_id}/investigate",
    response_model=InvestigationResponse,
)
def investigate_incident_endpoint(
    incident_id: int,
    request: InvestigateIncidentRequest,
    db: Session = Depends(get_db),
):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=422,
            detail="Investigation question cannot be blank.",
        )

    try:
        return investigate_incident(db, incident_id, question)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc