
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import SimulationRunRequest
from app.services.simulation_service import run_simulation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


@router.post("/run")
def run_simulation_endpoint(
    request: SimulationRunRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        return run_simulation(db, request.scenario_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Simulation failed")
        raise HTTPException(
            status_code=500,
            detail="Simulation failed. No simulation result was returned.",
        ) from exc
