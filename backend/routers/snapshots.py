"""
Snapshot Router — /api/snapshots

Provides endpoints for managing valuation snapshots per asset.
Each snapshot contains a complete set of inputs (phases, costs, commercial data)
and may contain calculation results (NPV, cashflows).

Endpoints:
    GET  /api/snapshots/{asset_id}                      — List snapshots for an asset
    GET  /api/snapshots/{asset_id}/{snapshot_id}         — Get full snapshot detail
    POST /api/snapshots/{asset_id}                       — Create new snapshot
    POST /api/snapshots/{asset_id}/{snapshot_id}/clone   — Deep-clone a snapshot
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud
from ..models import MCCommercialConfig, MCRDConfig, WhatIfPhaseLever, CommercialRow
from ..schemas import (
    SnapshotCreate, SnapshotResponse, SnapshotDetailResponse,
    PhaseInputSchema, RDCostSchema, CommercialRowSchema,
    MCCommercialConfigSchema, MCRDConfigSchema, WhatIfPhaseLeverSchema,
    SnapshotSettingsUpdate, SnapshotGeneralUpdate,
)

router = APIRouter(prefix="/api/snapshots", tags=["Snapshots"])


@router.get("/{asset_id}", response_model=list[SnapshotResponse])
def list_snapshots(asset_id: int, db: Session = Depends(get_db)):
    """List all snapshots for an asset, ordered by creation date (newest first)."""
    asset = crud.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return crud.list_snapshots(db, asset_id)


@router.get("/detail/{snapshot_id}")
def get_snapshot_detail_by_id(snapshot_id: int, db: Session = Depends(get_db)):
    """
    Get full snapshot detail by snapshot_id alone (no asset_id required).
    Used by the frontend which only has the snapshot_id in context.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    return _build_snapshot_detail(snapshot)


def _build_snapshot_detail(snapshot) -> dict:
    return {
        "id": snapshot.id,
        "asset_id": snapshot.asset_id,
        "snapshot_name": snapshot.snapshot_name,
        "description": snapshot.description,
        "valuation_year": snapshot.valuation_year,
        "horizon_years": snapshot.horizon_years,
        "wacc_rd": snapshot.wacc_rd,
        "approval_date": snapshot.approval_date,
        "mc_iterations": snapshot.mc_iterations,
        "random_seed": snapshot.random_seed,
        "whatif_revenue_lever": snapshot.whatif_revenue_lever,
        "whatif_rd_cost_lever": snapshot.whatif_rd_cost_lever,
        "npv_deterministic": snapshot.npv_deterministic,
        "npv_deterministic_whatif": snapshot.npv_deterministic_whatif,
        "npv_mc_average": snapshot.npv_mc_average,
        "npv_mc_p10": snapshot.npv_mc_p10,
        "npv_mc_p25": snapshot.npv_mc_p25,
        "npv_mc_p50": snapshot.npv_mc_p50,
        "npv_mc_p75": snapshot.npv_mc_p75,
        "npv_mc_p90": snapshot.npv_mc_p90,
        "mc_distribution_json": snapshot.mc_distribution_json,
        "created_at": snapshot.created_at.isoformat(),
        "phase_inputs": [
            {"phase_name": pi.phase_name, "start_date": pi.start_date, "success_rate": pi.success_rate}
            for pi in snapshot.phase_inputs
        ],
        "rd_costs": [
            {"year": rc.year, "phase_name": rc.phase_name, "rd_cost": rc.rd_cost}
            for rc in snapshot.rd_costs
        ],
        "commercial_rows": [
            {col.name: getattr(cr, col.name) for col in cr.__table__.columns if col.name not in ("id", "snapshot_id")}
            for cr in snapshot.commercial_rows
        ],
        "mc_commercial_config": (
            {col.name: getattr(snapshot.mc_commercial_config, col.name)
             for col in snapshot.mc_commercial_config.__table__.columns
             if col.name not in ("id", "snapshot_id")}
            if snapshot.mc_commercial_config else None
        ),
        "mc_rd_configs": [
            {
                "phase_name": mc.phase_name, "variable": mc.variable,
                "toggle": mc.toggle, "min_value": mc.min_value,
                "min_probability": mc.min_probability, "max_value": mc.max_value,
                "max_probability": mc.max_probability,
            }
            for mc in snapshot.mc_rd_configs
        ],
        "whatif_phase_levers": [
            {
                "phase_name": wl.phase_name, "lever_sr": wl.lever_sr,
                "lever_duration_months": wl.lever_duration_months,
            }
            for wl in snapshot.whatif_phase_levers
        ],
    }


@router.get("/{asset_id}/{snapshot_id}")
def get_snapshot_detail(asset_id: int, snapshot_id: int, db: Session = Depends(get_db)):
    """
    Get full snapshot detail with all child data (phases, costs, commercial, MC config).
    Returns a rich nested object for display or LLM consumption.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot or snapshot.asset_id != asset_id:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot {snapshot_id} not found for asset {asset_id}",
        )
    return _build_snapshot_detail(snapshot)


@router.post("/{asset_id}", response_model=SnapshotResponse, status_code=201)
def create_snapshot(asset_id: int, data: SnapshotCreate, db: Session = Depends(get_db)):
    """
    Create a new snapshot with all input data.
    
    The request body must include phase_inputs, rd_costs, and commercial_rows
    at minimum. MC config and what-if levers are optional.
    """
    asset = crud.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    
    try:
        snapshot = crud.create_snapshot(db, asset_id, data)
        return snapshot
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Snapshot '{data.snapshot_name}' already exists for asset {asset_id}",
        )


@router.post("/{asset_id}/{snapshot_id}/clone", response_model=SnapshotResponse, status_code=201)
def clone_snapshot(
    asset_id: int,
    snapshot_id: int,
    new_name: str = Query(..., description="Name for the cloned snapshot"),
    db: Session = Depends(get_db),
):
    """
    Deep-clone a snapshot with all child data.
    
    Copies: phase_inputs, rd_costs, commercial_rows, mc_config, whatif_levers.
    Does NOT copy: cashflows (results are cleared for recalculation).
    """
    try:
        cloned = crud.clone_snapshot(db, asset_id, snapshot_id, new_name)
        if not cloned:
            raise HTTPException(
                status_code=404,
                detail=f"Snapshot {snapshot_id} not found for asset {asset_id}",
            )
        return cloned
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Snapshot '{new_name}' already exists for asset {asset_id}",
        )


@router.patch("/{snapshot_id}/settings")
def update_snapshot_settings(
    snapshot_id: int, data: SnapshotSettingsUpdate, db: Session = Depends(get_db)
):
    """Update MC iterations and random seed on a snapshot."""
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    if data.mc_iterations is not None:
        snapshot.mc_iterations = data.mc_iterations
    if data.random_seed is not None:
        snapshot.random_seed = data.random_seed
    db.commit()
    return {"detail": "Settings updated", "mc_iterations": snapshot.mc_iterations, "random_seed": snapshot.random_seed}


@router.put("/{snapshot_id}/general")
def update_snapshot_general(
    snapshot_id: int, data: SnapshotGeneralUpdate, db: Session = Depends(get_db)
):
    """
    Update general snapshot parameters: name, description, valuation year,
    horizon, WACC R&D, approval date, MC iterations, random seed.

    Only fields that are provided (non-None) will be updated.
    """
    from sqlalchemy.exc import IntegrityError as _IE

    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    updatable = [
        "snapshot_name", "description", "valuation_year", "horizon_years",
        "wacc_rd", "approval_date", "mc_iterations", "random_seed",
    ]
    changed = []
    for field in updatable:
        value = getattr(data, field, None)
        if value is not None:
            setattr(snapshot, field, value)
            changed.append(field)

    try:
        db.commit()
    except _IE:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Snapshot name '{data.snapshot_name}' already exists for this asset",
        )

    return {
        "detail": f"Updated {len(changed)} field(s): {', '.join(changed) if changed else 'none'}",
        "snapshot_id": snapshot.id,
        "snapshot_name": snapshot.snapshot_name,
    }


@router.put("/{snapshot_id}/mc-config")
def upsert_mc_commercial_config(
    snapshot_id: int, data: MCCommercialConfigSchema, db: Session = Depends(get_db)
):
    """Create or replace the Monte Carlo commercial configuration for a snapshot."""
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    existing = db.query(MCCommercialConfig).filter(MCCommercialConfig.snapshot_id == snapshot_id).first()
    if existing:
        for field, value in data.model_dump().items():
            setattr(existing, field, value)
    else:
        db.add(MCCommercialConfig(snapshot_id=snapshot_id, **data.model_dump()))
    db.commit()
    return {"detail": "MC commercial config saved"}


@router.put("/{snapshot_id}/mc-rd-configs")
def replace_mc_rd_configs(
    snapshot_id: int, configs: list[MCRDConfigSchema], db: Session = Depends(get_db)
):
    """Replace all MC R&D configs for a snapshot (full replace)."""
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    db.query(MCRDConfig).filter(MCRDConfig.snapshot_id == snapshot_id).delete()
    for cfg in configs:
        db.add(MCRDConfig(snapshot_id=snapshot_id, **cfg.model_dump()))
    db.commit()
    return {"detail": f"Saved {len(configs)} R&D MC configs"}


# ---------------------------------------------------------------------------
# What-If Levers
# ---------------------------------------------------------------------------

from pydantic import BaseModel
from typing import Optional

class WhatIfLeversUpdate(BaseModel):
    """Request body for updating what-if levers on a snapshot."""
    whatif_revenue_lever: Optional[float] = None
    whatif_rd_cost_lever: Optional[float] = None
    phase_levers: Optional[list[WhatIfPhaseLeverSchema]] = None


@router.put("/{snapshot_id}/whatif-levers")
def update_whatif_levers(
    snapshot_id: int, data: WhatIfLeversUpdate, db: Session = Depends(get_db)
):
    """
    Save what-if lever values on a snapshot.

    Updates the snapshot's revenue and R&D cost levers, and replaces
    all phase-level what-if levers (SR overrides and duration shifts).
    Must be called BEFORE running the what-if NPV calculation.
    """
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")

    # Update snapshot-level levers
    if data.whatif_revenue_lever is not None:
        snapshot.whatif_revenue_lever = data.whatif_revenue_lever
    if data.whatif_rd_cost_lever is not None:
        snapshot.whatif_rd_cost_lever = data.whatif_rd_cost_lever

    # Replace phase-level levers (full replace)
    if data.phase_levers is not None:
        db.query(WhatIfPhaseLever).filter(
            WhatIfPhaseLever.snapshot_id == snapshot_id
        ).delete()
        for pl in data.phase_levers:
            db.add(WhatIfPhaseLever(
                snapshot_id=snapshot_id,
                phase_name=pl.phase_name,
                lever_sr=pl.lever_sr,
                lever_duration_months=pl.lever_duration_months,
            ))

    db.commit()
    return {
        "detail": "What-if levers saved",
        "whatif_revenue_lever": snapshot.whatif_revenue_lever,
        "whatif_rd_cost_lever": snapshot.whatif_rd_cost_lever,
        "phase_levers_count": len(data.phase_levers) if data.phase_levers else 0,
    }


# ---------------------------------------------------------------------------
# Commercial Rows Management
# ---------------------------------------------------------------------------

@router.post("/{snapshot_id}/commercial-rows")
def add_commercial_row(
    snapshot_id: int, data: CommercialRowSchema, db: Session = Depends(get_db)
):
    """Add a single commercial row to an existing snapshot."""
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    row = CommercialRow(snapshot_id=snapshot_id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "detail": "Commercial row added",
        "id": row.id,
        "region": row.region,
        "scenario": row.scenario,
        "segment_name": row.segment_name,
    }


@router.put("/{snapshot_id}/commercial-rows")
def replace_commercial_rows(
    snapshot_id: int, rows: list[CommercialRowSchema], db: Session = Depends(get_db)
):
    """Replace ALL commercial rows for a snapshot (full replace)."""
    snapshot = crud.get_snapshot(db, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    db.query(CommercialRow).filter(CommercialRow.snapshot_id == snapshot_id).delete()
    for row_data in rows:
        db.add(CommercialRow(snapshot_id=snapshot_id, **row_data.model_dump()))
    db.commit()
    return {"detail": f"Saved {len(rows)} commercial rows"}


@router.delete("/{snapshot_id}/commercial-rows/{row_id}")
def delete_commercial_row(
    snapshot_id: int, row_id: int, db: Session = Depends(get_db)
):
    """Delete a single commercial row by ID."""
    row = db.query(CommercialRow).filter(
        CommercialRow.id == row_id,
        CommercialRow.snapshot_id == snapshot_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Commercial row {row_id} not found")
    db.delete(row)
    db.commit()
    return {"detail": f"Commercial row {row_id} deleted"}


