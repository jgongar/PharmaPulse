"""CRUD operations for PharmaPulse."""

import json
from sqlalchemy.orm import Session, joinedload

from . import models, schemas


# ---- Assets ----

def get_assets(db: Session) -> list[models.Asset]:
    return db.query(models.Asset).order_by(models.Asset.id).all()


def get_asset(db: Session, asset_id: int) -> models.Asset | None:
    return db.query(models.Asset).filter(models.Asset.id == asset_id).first()


def create_asset(db: Session, data: schemas.AssetCreate) -> models.Asset:
    asset = models.Asset(**data.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def update_asset(db: Session, asset_id: int, data: schemas.AssetUpdate) -> models.Asset | None:
    asset = get_asset(db, asset_id)
    if not asset:
        return None
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(asset, k, v)
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, asset_id: int) -> bool:
    asset = get_asset(db, asset_id)
    if not asset:
        return False
    db.delete(asset)
    db.commit()
    return True


# ---- Snapshots ----

def _load_snapshot(db: Session, snapshot_id: int) -> models.Snapshot | None:
    return (
        db.query(models.Snapshot)
        .options(
            joinedload(models.Snapshot.phase_inputs),
            joinedload(models.Snapshot.rd_costs),
            joinedload(models.Snapshot.commercial_rows),
            joinedload(models.Snapshot.cashflows),
            joinedload(models.Snapshot.mc_config),
            joinedload(models.Snapshot.whatif_levers),
        )
        .filter(models.Snapshot.id == snapshot_id)
        .first()
    )


def get_snapshots_for_asset(db: Session, asset_id: int) -> list[models.Snapshot]:
    return (
        db.query(models.Snapshot)
        .options(
            joinedload(models.Snapshot.phase_inputs),
            joinedload(models.Snapshot.rd_costs),
            joinedload(models.Snapshot.commercial_rows),
            joinedload(models.Snapshot.cashflows),
            joinedload(models.Snapshot.mc_config),
            joinedload(models.Snapshot.whatif_levers),
        )
        .filter(models.Snapshot.asset_id == asset_id)
        .order_by(models.Snapshot.version)
        .all()
    )


def get_snapshot(db: Session, snapshot_id: int) -> models.Snapshot | None:
    return _load_snapshot(db, snapshot_id)


def _sync_children(db: Session, snapshot: models.Snapshot, data: dict):
    """Replace child collections from input data."""
    # Phase inputs
    if "phase_inputs" in data and data["phase_inputs"] is not None:
        for old in snapshot.phase_inputs:
            db.delete(old)
        snapshot.phase_inputs = [
            models.PhaseInput(snapshot_id=snapshot.id, **pi)
            for pi in data["phase_inputs"]
        ]

    # RD costs
    if "rd_costs" in data and data["rd_costs"] is not None:
        for old in snapshot.rd_costs:
            db.delete(old)
        snapshot.rd_costs = [
            models.RDCost(snapshot_id=snapshot.id, **rc)
            for rc in data["rd_costs"]
        ]

    # Commercial rows
    if "commercial_rows" in data and data["commercial_rows"] is not None:
        for old in snapshot.commercial_rows:
            db.delete(old)
        snapshot.commercial_rows = [
            models.CommercialRow(snapshot_id=snapshot.id, **cr)
            for cr in data["commercial_rows"]
        ]

    # MC config
    if "mc_config" in data and data["mc_config"] is not None:
        if snapshot.mc_config:
            db.delete(snapshot.mc_config)
        snapshot.mc_config = models.MCConfig(snapshot_id=snapshot.id, **data["mc_config"])

    # What-if levers
    if "whatif_levers" in data and data["whatif_levers"] is not None:
        if snapshot.whatif_levers:
            db.delete(snapshot.whatif_levers)
        levers = data["whatif_levers"].copy()
        if "pos_override" in levers and isinstance(levers["pos_override"], dict):
            levers["pos_override"] = json.dumps(levers["pos_override"])
        snapshot.whatif_levers = models.WhatIfLevers(snapshot_id=snapshot.id, **levers)


def create_snapshot(db: Session, data: schemas.SnapshotCreate) -> models.Snapshot:
    d = data.model_dump()
    children_keys = ["phase_inputs", "rd_costs", "commercial_rows", "mc_config", "whatif_levers"]
    children = {k: d.pop(k) for k in children_keys}

    # Auto-version
    existing = db.query(models.Snapshot).filter(models.Snapshot.asset_id == d["asset_id"]).count()
    d["version"] = existing + 1

    snapshot = models.Snapshot(**d)
    db.add(snapshot)
    db.flush()

    _sync_children(db, snapshot, children)
    db.commit()
    db.refresh(snapshot)
    return _load_snapshot(db, snapshot.id)


def update_snapshot(db: Session, snapshot_id: int, data: schemas.SnapshotUpdate) -> models.Snapshot | None:
    snapshot = _load_snapshot(db, snapshot_id)
    if not snapshot:
        return None

    d = data.model_dump(exclude_unset=True)
    children_keys = ["phase_inputs", "rd_costs", "commercial_rows", "mc_config", "whatif_levers"]
    children = {k: d.pop(k) for k in children_keys if k in d}

    for k, v in d.items():
        setattr(snapshot, k, v)

    _sync_children(db, snapshot, children)
    db.commit()
    return _load_snapshot(db, snapshot_id)


def delete_snapshot(db: Session, snapshot_id: int) -> bool:
    snapshot = get_snapshot(db, snapshot_id)
    if not snapshot:
        return False
    db.delete(snapshot)
    db.commit()
    return True


def save_cashflows(db: Session, snapshot_id: int, cashflows: list[dict]):
    """Replace cashflow rows for a snapshot."""
    db.query(models.CashflowRow).filter(models.CashflowRow.snapshot_id == snapshot_id).delete()
    for cf in cashflows:
        db.add(models.CashflowRow(snapshot_id=snapshot_id, **cf))
    db.commit()


# ---- Portfolios ----

def get_portfolios(db: Session) -> list[models.Portfolio]:
    return db.query(models.Portfolio).options(joinedload(models.Portfolio.members)).all()


def get_portfolio(db: Session, portfolio_id: int) -> models.Portfolio | None:
    return (
        db.query(models.Portfolio)
        .options(joinedload(models.Portfolio.members))
        .filter(models.Portfolio.id == portfolio_id)
        .first()
    )


def create_portfolio(db: Session, data: schemas.PortfolioCreate) -> models.Portfolio:
    portfolio = models.Portfolio(name=data.name, description=data.description)
    db.add(portfolio)
    db.flush()
    for sid in data.snapshot_ids:
        db.add(models.PortfolioMember(portfolio_id=portfolio.id, snapshot_id=sid))
    db.commit()
    db.refresh(portfolio)
    return get_portfolio(db, portfolio.id)


def delete_portfolio(db: Session, portfolio_id: int) -> bool:
    p = get_portfolio(db, portfolio_id)
    if not p:
        return False
    db.delete(p)
    db.commit()
    return True
