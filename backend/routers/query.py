"""
Query Router — /api/query

Provides data query endpoints optimized for MCP tools and chat.
These endpoints return data in formats that are easy for LLMs to consume.

Endpoints:
    GET /api/query/assets                        — Search/filter assets
    GET /api/query/cashflows/{snapshot_id}        — Get cashflows with filters
    GET /api/query/portfolio-summary/{portfolio_id} — Concise portfolio summary
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud
from ..models import Asset, Cashflow, Snapshot, Portfolio, PortfolioProject, PortfolioResult

router = APIRouter(prefix="/api/query", tags=["Data Queries"])


@router.get("/assets")
def search_assets(
    compound_name: Optional[str] = Query(None, description="Partial match on compound name"),
    therapeutic_area: Optional[str] = Query(None, description="Exact match on TA"),
    current_phase: Optional[str] = Query(None, description="Exact match on phase"),
    is_internal: Optional[bool] = Query(None, description="Filter internal/competitor"),
    min_npv: Optional[float] = Query(None, description="Minimum deterministic NPV"),
    max_npv: Optional[float] = Query(None, description="Maximum deterministic NPV"),
    db: Session = Depends(get_db),
):
    """
    Search and filter assets. Designed for MCP/chat tool consumption.
    Returns a list of assets matching the given criteria.
    """
    assets = crud.list_assets(
        db,
        compound_name=compound_name,
        therapeutic_area=therapeutic_area,
        current_phase=current_phase,
        is_internal=is_internal,
        min_npv=min_npv,
        max_npv=max_npv,
    )
    return [
        {
            "id": a.id,
            "sponsor": a.sponsor,
            "compound_name": a.compound_name,
            "moa": a.moa,
            "therapeutic_area": a.therapeutic_area,
            "indication": a.indication,
            "current_phase": a.current_phase,
            "is_internal": a.is_internal,
            "peak_sales_estimate": a.peak_sales_estimate,
            "launch_date": a.launch_date,
            "npv_deterministic": a.npv_deterministic,
            "npv_mc_average": a.npv_mc_average,
            "pathway": a.pathway,
            "biomarker": a.biomarker,
            "innovation_class": a.innovation_class,
        }
        for a in assets
    ]


@router.get("/cashflows/{snapshot_id}")
def get_cashflows(
    snapshot_id: int,
    scope: Optional[str] = Query(None, description="Filter by scope (R&D, US, EU, etc.)"),
    start_year: Optional[int] = Query(None, description="Start year filter"),
    end_year: Optional[int] = Query(None, description="End year filter"),
    db: Session = Depends(get_db),
):
    """
    Get calculated cashflows for a snapshot, with optional filters.
    Returns cashflow rows for LLM consumption or chart rendering.
    """
    snapshot = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    
    query = db.query(Cashflow).filter(Cashflow.snapshot_id == snapshot_id)
    
    if scope:
        query = query.filter(Cashflow.scope == scope)
    if start_year:
        query = query.filter(Cashflow.year >= start_year)
    if end_year:
        query = query.filter(Cashflow.year <= end_year)
    
    cashflows = query.order_by(Cashflow.cashflow_type, Cashflow.scope, Cashflow.year).all()
    
    return [
        {
            "cashflow_type": cf.cashflow_type,
            "scope": cf.scope,
            "year": cf.year,
            "revenue": round(cf.revenue, 2),
            "costs": round(cf.costs, 2),
            "tax": round(cf.tax, 2),
            "fcf_risk_adj": round(cf.fcf_risk_adj, 2),
            "fcf_pv": round(cf.fcf_pv, 2),
            "risk_multiplier": round(cf.risk_multiplier, 4),
        }
        for cf in cashflows
    ]


@router.get("/portfolio-summary/{portfolio_id}")
def get_portfolio_summary(portfolio_id: int, db: Session = Depends(get_db)):
    """
    Get a concise portfolio summary for LLM consumption.
    Returns portfolio name, NPV, project list with key metrics.
    """
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    projects = []
    for proj in portfolio.projects:
        result = (
            db.query(PortfolioResult)
            .filter(
                PortfolioResult.portfolio_id == portfolio_id,
                PortfolioResult.asset_id == proj.asset_id,
            )
            .first()
        )
        projects.append({
            "compound_name": proj.asset.compound_name,
            "therapeutic_area": proj.asset.therapeutic_area,
            "indication": proj.asset.indication,
            "current_phase": proj.asset.current_phase,
            "is_active": proj.is_active,
            "npv_used": result.npv_used if result else (
                proj.snapshot.npv_deterministic if proj.snapshot else None
            ),
        })
    
    return {
        "portfolio_name": portfolio.portfolio_name,
        "portfolio_type": portfolio.portfolio_type,
        "total_npv": portfolio.total_npv,
        "project_count": len(portfolio.projects),
        "active_projects": sum(1 for p in portfolio.projects if p.is_active),
        "projects": projects,
    }


