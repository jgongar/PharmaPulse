"""
Asset CRUD Router — /api/portfolio

Provides endpoints for managing individual drug assets (internal + competitor).
This is the asset-level CRUD, distinct from the portfolio-level management
in portfolios.py.

Endpoints:
    GET    /api/portfolio          — List all assets with optional filters
    POST   /api/portfolio          — Create a new asset
    PUT    /api/portfolio/{id}     — Update an asset
    DELETE /api/portfolio/{id}     — Delete an asset (cascades to snapshots)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud
from ..schemas import AssetCreate, AssetUpdate, AssetResponse

router = APIRouter(prefix="/api/portfolio", tags=["Assets"])


@router.get("", response_model=list[AssetResponse])
def list_assets(
    is_internal: Optional[bool] = Query(None, description="Filter by internal/competitor"),
    therapeutic_area: Optional[str] = Query(None, description="Filter by therapeutic area"),
    db: Session = Depends(get_db),
):
    """
    List all drug assets with optional filters.
    
    Query Parameters:
        is_internal: True for internal only, False for competitors only
        therapeutic_area: Exact match on therapeutic area
    """
    assets = crud.list_assets(db, is_internal=is_internal, therapeutic_area=therapeutic_area)
    return assets


@router.post("", response_model=AssetResponse, status_code=201)
def create_asset(data: AssetCreate, db: Session = Depends(get_db)):
    """
    Create a new drug asset.
    
    Returns 409 if (sponsor, compound_name, indication) already exists.
    """
    try:
        asset = crud.create_asset(db, data)
        return asset
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "detail": f"Asset already exists: {data.sponsor}/{data.compound_name}/{data.indication}",
                "error_code": "DUPLICATE_ASSET",
                "context": {
                    "sponsor": data.sponsor,
                    "compound_name": data.compound_name,
                    "indication": data.indication,
                },
            },
        )


@router.get("/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    """Get a single asset by ID."""
    asset = crud.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return asset


@router.put("/{asset_id}", response_model=AssetResponse)
def update_asset(asset_id: int, data: AssetUpdate, db: Session = Depends(get_db)):
    """Update an existing asset. Only provided fields are updated."""
    asset = crud.update_asset(db, asset_id, data)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return asset


@router.delete("/{asset_id}", status_code=200)
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    """
    Delete an asset and all its snapshots (CASCADE delete).
    Returns confirmation message.
    """
    deleted = crud.delete_asset(db, asset_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return {"detail": f"Asset {asset_id} deleted successfully"}


