"""Monte Carlo simulation endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud, schemas
from ..engines.montecarlo import run_monte_carlo

router = APIRouter(prefix="/api/mc", tags=["monte-carlo"])


@router.post("/run/{snapshot_id}", response_model=schemas.MCResult)
def monte_carlo_simulation(snapshot_id: int, db: Session = Depends(get_db)):
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    result = run_monte_carlo(db, snapshot)
    return result
