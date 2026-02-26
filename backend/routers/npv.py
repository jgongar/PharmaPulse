"""
NPV Calculation Router — /api/npv

Provides endpoints for running NPV calculations on asset snapshots.
Calculation logic is in backend/engines/ — these endpoints just
orchestrate the call and return results.

Endpoints:
    POST /api/npv/deterministic/{snapshot_id}        — Run deterministic rNPV
    POST /api/npv/deterministic-whatif/{snapshot_id}  — Run deterministic rNPV with what-if levers
    POST /api/npv/montecarlo/{snapshot_id}            — Run Monte Carlo simulation
    GET  /api/npv/cashflows/{snapshot_id}             — Retrieve stored cashflows
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud
from ..models import Cashflow

router = APIRouter(prefix="/api/npv", tags=["NPV Calculations"])


@router.post("/deterministic/{snapshot_id}")
def run_deterministic_npv(snapshot_id: int, db: Session = Depends(get_db)):
    """
    Run deterministic rNPV calculation for a snapshot.
    
    Calculates risk-adjusted NPV using all financial rules (Section 5 of spec).
    Stores cashflows in the database and updates the snapshot record.
    
    Returns NPV results and cashflow summary.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    try:
        from ..engines.deterministic import calculate_deterministic_npv
        result = calculate_deterministic_npv(snapshot_id, db, is_whatif=False)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deterministic-whatif/{snapshot_id}")
def run_deterministic_whatif(snapshot_id: int, db: Session = Depends(get_db)):
    """
    Run deterministic rNPV calculation with what-if levers applied.
    
    Uses the same engine as /deterministic but applies:
    - Revenue lever (multiplier on all commercial revenue)
    - R&D cost lever (multiplier on all R&D costs)
    - Phase SR overrides and duration shifts
    
    Results are stored separately as "deterministic_whatif" cashflow type.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    try:
        from ..engines.deterministic import calculate_deterministic_npv
        result = calculate_deterministic_npv(snapshot_id, db, is_whatif=True)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/montecarlo/{snapshot_id}")
def run_monte_carlo(snapshot_id: int, db: Session = Depends(get_db)):
    """
    Run Monte Carlo simulation for a snapshot.
    
    Performs N iterations of randomized NPV calculation.
    Returns average NPV, percentiles, and full distribution.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    try:
        from ..engines.montecarlo import run_monte_carlo as mc_engine
        result = mc_engine(snapshot_id, db)
        return result
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Monte Carlo engine not yet implemented (Phase C)",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cashflows/{snapshot_id}")
def get_cashflows(
    snapshot_id: int,
    cashflow_type: str = Query("deterministic", description="Type of cashflows to retrieve"),
    scope: str = Query(None, description="Filter by scope (R&D, US, EU, ROW, Total)"),
    db: Session = Depends(get_db),
):
    """
    Retrieve stored cashflows for a snapshot.
    
    Returns all cashflow rows for the given snapshot_id and type,
    optionally filtered by scope.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    query = db.query(Cashflow).filter(
        Cashflow.snapshot_id == snapshot_id,
        Cashflow.cashflow_type == cashflow_type,
    )
    
    if scope:
        query = query.filter(Cashflow.scope == scope)
    
    cashflows = query.order_by(Cashflow.year, Cashflow.scope).all()
    
    return {
        "snapshot_id": snapshot_id,
        "cashflow_type": cashflow_type,
        "count": len(cashflows),
        "cashflows": [
            {
                "year": cf.year,
                "scope": cf.scope,
                "revenue": cf.revenue,
                "costs": cf.costs,
                "tax": cf.tax,
                "fcf_non_risk_adj": cf.fcf_non_risk_adj,
                "risk_multiplier": cf.risk_multiplier,
                "fcf_risk_adj": cf.fcf_risk_adj,
                "fcf_pv": cf.fcf_pv,
            }
            for cf in cashflows
        ],
    }

