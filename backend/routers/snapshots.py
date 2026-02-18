"""Snapshot CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud, schemas

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


@router.get("/asset/{asset_id}", response_model=list[schemas.SnapshotOut])
def list_snapshots(asset_id: int, db: Session = Depends(get_db)):
    return crud.get_snapshots_for_asset(db, asset_id)


@router.get("/{snapshot_id}", response_model=schemas.SnapshotOut)
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    snap = crud.get_snapshot(db, snapshot_id)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    return snap


@router.post("/", response_model=schemas.SnapshotOut, status_code=201)
def create_snapshot(data: schemas.SnapshotCreate, db: Session = Depends(get_db)):
    asset = crud.get_asset(db, data.asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    return crud.create_snapshot(db, data)


@router.put("/{snapshot_id}", response_model=schemas.SnapshotOut)
def update_snapshot(snapshot_id: int, data: schemas.SnapshotUpdate, db: Session = Depends(get_db)):
    snap = crud.update_snapshot(db, snapshot_id, data)
    if not snap:
        raise HTTPException(404, "Snapshot not found")
    return snap


@router.delete("/{snapshot_id}")
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    if not crud.delete_snapshot(db, snapshot_id):
        raise HTTPException(404, "Snapshot not found")
    return {"ok": True}
