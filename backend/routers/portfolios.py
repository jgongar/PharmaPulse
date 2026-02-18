"""Portfolio CRUD and analysis endpoints."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud, schemas
from ..engines.portfolio import portfolio_summary, portfolio_monte_carlo, portfolio_cashflow_timeline

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


@router.get("/", response_model=list[schemas.PortfolioOut])
def list_portfolios(db: Session = Depends(get_db)):
    portfolios = crud.get_portfolios(db)
    result = []
    for p in portfolios:
        result.append(schemas.PortfolioOut(
            id=p.id, name=p.name, description=p.description,
            created_at=p.created_at,
            snapshot_ids=[m.snapshot_id for m in p.members],
        ))
    return result


@router.post("/", response_model=schemas.PortfolioOut, status_code=201)
def create_portfolio(data: schemas.PortfolioCreate, db: Session = Depends(get_db)):
    p = crud.create_portfolio(db, data)
    return schemas.PortfolioOut(
        id=p.id, name=p.name, description=p.description,
        created_at=p.created_at,
        snapshot_ids=[m.snapshot_id for m in p.members],
    )


@router.delete("/{portfolio_id}")
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    if not crud.delete_portfolio(db, portfolio_id):
        raise HTTPException(404, "Portfolio not found")
    return {"ok": True}


@router.get("/{portfolio_id}/summary")
def get_portfolio_summary(portfolio_id: int, db: Session = Depends(get_db)):
    p = crud.get_portfolio(db, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return portfolio_summary(db, p)


@router.post("/{portfolio_id}/montecarlo")
def run_portfolio_mc(
    portfolio_id: int,
    n_iterations: int = Query(10000, ge=1000, le=100000),
    correlation: float = Query(0.0, ge=0.0, le=1.0),
    seed: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    p = crud.get_portfolio(db, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return portfolio_monte_carlo(db, p, n_iterations, correlation, seed)


@router.get("/{portfolio_id}/cashflows")
def get_portfolio_cashflows(portfolio_id: int, db: Session = Depends(get_db)):
    p = crud.get_portfolio(db, portfolio_id)
    if not p:
        raise HTTPException(404, "Portfolio not found")
    return portfolio_cashflow_timeline(db, p)
