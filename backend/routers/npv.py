"""NPV calculation endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud, schemas
from ..engines.deterministic import run_deterministic_npv

router = APIRouter(prefix="/api/npv", tags=["npv"])


@router.post("/deterministic/{snapshot_id}", response_model=schemas.NPVResult)
def deterministic_npv(snapshot_id: int, db: Session = Depends(get_db)):
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(404, "Snapshot not found")
    result = run_deterministic_npv(db, snapshot)
    return result
