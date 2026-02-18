"""Asset CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud, schemas

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/", response_model=list[schemas.AssetOut])
def list_assets(db: Session = Depends(get_db)):
    return crud.get_assets(db)


@router.get("/{asset_id}", response_model=schemas.AssetOut)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = crud.get_asset(db, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset


@router.post("/", response_model=schemas.AssetOut, status_code=201)
def create_asset(data: schemas.AssetCreate, db: Session = Depends(get_db)):
    return crud.create_asset(db, data)


@router.put("/{asset_id}", response_model=schemas.AssetOut)
def update_asset(asset_id: int, data: schemas.AssetUpdate, db: Session = Depends(get_db)):
    asset = crud.update_asset(db, asset_id, data)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return asset


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    if not crud.delete_asset(db, asset_id):
        raise HTTPException(404, "Asset not found")
    return {"ok": True}
