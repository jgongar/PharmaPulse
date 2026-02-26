"""
Portfolio Management Router — /api/portfolios

Provides endpoints for creating and managing portfolios of projects,
running portfolio simulations, comparing scenarios, and managing
simulation runs (save/restore/compare — v5).

Endpoints:
    GET    /api/portfolios                                  — List all portfolios
    GET    /api/portfolios/{id}                              — Get portfolio detail
    POST   /api/portfolios                                   — Create portfolio
    DELETE /api/portfolios/{id}                               — Delete portfolio
    POST   /api/portfolios/{id}/projects                     — Add project
    DELETE /api/portfolios/{id}/projects/{asset_id}           — Remove project
    PUT    /api/portfolios/{id}/projects/{asset_id}/deactivate — Cancel project
    PUT    /api/portfolios/{id}/projects/{asset_id}/activate   — Reactivate project
    POST   /api/portfolios/{id}/overrides                    — Add override
    DELETE /api/portfolios/{id}/overrides/{override_id}       — Remove override
    POST   /api/portfolios/{id}/added-projects               — Add hypothetical project
    POST   /api/portfolios/{id}/simulate                     — Run simulation
    GET    /api/portfolios/compare                           — Compare portfolios
    POST   /api/portfolios/{id}/bd-placeholders              — Add BD placeholder
    DELETE /api/portfolios/{id}/bd-placeholders/{bd_id}       — Remove BD placeholder
    
    # Simulation Runs (v5)
    POST   /api/portfolios/{id}/runs                         — Save simulation run
    GET    /api/portfolios/{id}/runs                          — List saved runs
    GET    /api/portfolios/{id}/runs/{run_id}                 — Get run detail
    DELETE /api/portfolios/{id}/runs/{run_id}                 — Delete run
    PUT    /api/portfolios/{id}/runs/{run_id}                 — Update run metadata
    POST   /api/portfolios/{id}/runs/{run_id}/restore         — Restore run
    GET    /api/portfolios/compare-runs                       — Compare two runs
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from .. import crud
from ..models import (
    Portfolio, PortfolioProject, PortfolioScenarioOverride,
    PortfolioResult, PortfolioAddedProject, PortfolioBDPlaceholder,
)
from ..schemas import (
    PortfolioCreate, PortfolioProjectAdd, OverrideCreate,
    AddedProjectCreate, BDPlaceholderCreate,
    SimulationRunCreate, SimulationRunUpdate,
)

router = APIRouter(prefix="/api/portfolios", tags=["Portfolios"])


# ---------------------------------------------------------------------------
# PORTFOLIO CRUD
# ---------------------------------------------------------------------------

@router.get("")
def list_portfolios(db: Session = Depends(get_db)):
    """
    List all portfolios with project count, saved runs count, and latest run info (v5).
    Enables LLM to answer "show me all portfolios" in a single call.
    """
    return crud.list_portfolios(db)


@router.get("/compare")
def compare_portfolios(
    ids: str = Query(..., description="Comma-separated portfolio IDs, e.g. '1,2'"),
    db: Session = Depends(get_db),
):
    """Compare two portfolios side-by-side. Query: ?ids=X,Y"""
    try:
        id_list = [int(x.strip()) for x in ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid portfolio IDs format. Use: ?ids=1,2")
    
    if len(id_list) != 2:
        raise HTTPException(status_code=400, detail="Exactly 2 portfolio IDs required")
    
    p1 = crud.get_portfolio(db, id_list[0])
    p2 = crud.get_portfolio(db, id_list[1])
    if not p1:
        raise HTTPException(status_code=404, detail=f"Portfolio {id_list[0]} not found")
    if not p2:
        raise HTTPException(status_code=404, detail=f"Portfolio {id_list[1]} not found")
    
    # Build comparison
    npv1 = p1.total_npv or 0
    npv2 = p2.total_npv or 0
    return {
        "portfolio_a": {"id": p1.id, "name": p1.portfolio_name, "total_npv": npv1},
        "portfolio_b": {"id": p2.id, "name": p2.portfolio_name, "total_npv": npv2},
        "delta": {
            "npv_delta": npv2 - npv1,
            "npv_delta_pct": ((npv2 - npv1) / abs(npv1) * 100) if npv1 != 0 else 0,
        },
    }


@router.get("/compare-runs")
def compare_simulation_runs(
    run_ids: str = Query(..., description="Comma-separated run IDs, e.g. '1,2'"),
    db: Session = Depends(get_db),
):
    """Compare two saved simulation runs side-by-side (v5)."""
    try:
        id_list = [int(x.strip()) for x in run_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run IDs format")
    
    if len(id_list) != 2:
        raise HTTPException(status_code=400, detail="Exactly 2 run IDs required")
    
    run_a = crud.get_simulation_run(db, id_list[0])
    run_b = crud.get_simulation_run(db, id_list[1])
    if not run_a:
        raise HTTPException(status_code=404, detail=f"Run {id_list[0]} not found")
    if not run_b:
        raise HTTPException(status_code=404, detail=f"Run {id_list[1]} not found")
    
    # Parse frozen results for per-asset comparison
    results_a = json.loads(run_a.results_snapshot_json)
    results_b = json.loads(run_b.results_snapshot_json)
    
    # Build per-asset comparison
    assets_a = {r["compound_name"]: r for r in results_a}
    assets_b = {r["compound_name"]: r for r in results_b}
    all_names = sorted(set(list(assets_a.keys()) + list(assets_b.keys())))
    
    per_asset = []
    for name in all_names:
        npv_a = assets_a.get(name, {}).get("npv_used", 0)
        npv_b = assets_b.get(name, {}).get("npv_used", 0)
        per_asset.append({
            "compound_name": name,
            "npv_run_a": npv_a,
            "npv_run_b": npv_b,
            "delta": npv_b - npv_a,
        })
    
    portfolio_a = db.query(Portfolio).filter(Portfolio.id == run_a.portfolio_id).first()
    portfolio_b = db.query(Portfolio).filter(Portfolio.id == run_b.portfolio_id).first()
    
    overrides_a = json.loads(run_a.overrides_snapshot_json)
    overrides_b = json.loads(run_b.overrides_snapshot_json)
    
    return {
        "run_a": {
            "run_id": run_a.id, "run_name": run_a.run_name,
            "total_npv": run_a.total_npv,
            "portfolio_name": portfolio_a.portfolio_name if portfolio_a else "Unknown",
            "overrides_count": len(overrides_a),
            "timestamp": run_a.run_timestamp.isoformat(),
        },
        "run_b": {
            "run_id": run_b.id, "run_name": run_b.run_name,
            "total_npv": run_b.total_npv,
            "portfolio_name": portfolio_b.portfolio_name if portfolio_b else "Unknown",
            "overrides_count": len(overrides_b),
            "timestamp": run_b.run_timestamp.isoformat(),
        },
        "delta": {
            "npv_delta": run_b.total_npv - run_a.total_npv,
            "npv_delta_pct": (
                (run_b.total_npv - run_a.total_npv) / abs(run_a.total_npv) * 100
                if run_a.total_npv != 0 else 0
            ),
        },
        "per_asset_comparison": per_asset,
    }


@router.get("/{portfolio_id}")
def get_portfolio_detail(portfolio_id: int, db: Session = Depends(get_db)):
    """
    Get full portfolio detail including projects, overrides, added projects,
    BD placeholders, and all saved simulation runs (v5).
    """
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    # Build projects list
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
            "portfolio_project_id": proj.id,
            "asset_id": proj.asset_id,
            "compound_name": proj.asset.compound_name,
            "is_active": proj.is_active,
            "snapshot_id": proj.snapshot_id,
            "npv_simulated": result.npv_simulated if result else None,
            "npv_original": result.npv_original if result else (
                proj.snapshot.npv_deterministic if proj.snapshot else None
            ),
        })
    
    # Build overrides list
    overrides = []
    for proj in portfolio.projects:
        for ov in proj.overrides:
            overrides.append({
                "override_id": ov.id,
                "project_id": proj.id,
                "compound_name": proj.asset.compound_name,
                "override_type": ov.override_type,
                "override_value": ov.override_value,
                "phase_name": ov.phase_name,
                "description": ov.description,
            })
    
    # Build added projects
    added = [
        {
            "id": ap.id, "compound_name": ap.compound_name,
            "therapeutic_area": ap.therapeutic_area,
            "indication": ap.indication, "current_phase": ap.current_phase,
            "peak_sales": ap.peak_sales, "npv_calculated": ap.npv_calculated,
        }
        for ap in portfolio.added_projects
    ]
    
    # Build BD placeholders
    bds = [
        {
            "id": bd.id, "deal_name": bd.deal_name, "deal_type": bd.deal_type,
            "therapeutic_area": bd.therapeutic_area,
            "current_phase": bd.current_phase, "peak_sales": bd.peak_sales,
            "npv_calculated": bd.npv_calculated,
        }
        for bd in portfolio.bd_placeholders
    ]
    
    # Build saved runs (v5)
    saved_runs = [
        {
            "run_id": run.id, "run_name": run.run_name,
            "total_npv": run.total_npv,
            "run_timestamp": run.run_timestamp.isoformat(),
            "notes": run.notes,
            "overrides_count": len(json.loads(run.overrides_snapshot_json)) if run.overrides_snapshot_json else 0,
        }
        for run in portfolio.simulation_runs
    ]
    
    return {
        "id": portfolio.id,
        "portfolio_name": portfolio.portfolio_name,
        "portfolio_type": portfolio.portfolio_type,
        "base_portfolio_id": portfolio.base_portfolio_id,
        "total_npv": portfolio.total_npv,
        "total_rd_cost_json": portfolio.total_rd_cost_json,
        "total_sales_json": portfolio.total_sales_json,
        "created_at": portfolio.created_at.isoformat(),
        "projects": projects,
        "overrides": overrides,
        "added_projects": added,
        "bd_placeholders": bds,
        "saved_runs": saved_runs,
    }


@router.post("", status_code=201)
def create_portfolio(data: PortfolioCreate, db: Session = Depends(get_db)):
    """
    Create a new portfolio. Optionally include asset_ids for bulk project addition (v5).
    
    For scenario portfolios, base_portfolio_id is required.
    """
    if data.portfolio_type == "scenario" and not data.base_portfolio_id:
        raise HTTPException(
            status_code=400,
            detail="Scenario portfolio must reference a base_portfolio_id",
        )
    if data.base_portfolio_id:
        base = db.query(Portfolio).filter(Portfolio.id == data.base_portfolio_id).first()
        if not base:
            raise HTTPException(
                status_code=404,
                detail=f"Base portfolio {data.base_portfolio_id} not found",
            )
    
    try:
        portfolio = crud.create_portfolio(db, data)
        return {
            "id": portfolio.id,
            "portfolio_name": portfolio.portfolio_name,
            "portfolio_type": portfolio.portfolio_type,
            "project_count": len(portfolio.projects),
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Portfolio '{data.portfolio_name}' already exists",
        )


@router.delete("/{portfolio_id}", status_code=200)
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    """Delete a portfolio and all its child data (CASCADE)."""
    deleted = crud.delete_portfolio(db, portfolio_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    return {"detail": f"Portfolio {portfolio_id} deleted"}


# ---------------------------------------------------------------------------
# PORTFOLIO PROJECTS
# ---------------------------------------------------------------------------

@router.post("/{portfolio_id}/projects", status_code=201)
def add_project(portfolio_id: int, data: PortfolioProjectAdd, db: Session = Depends(get_db)):
    """Add a project (asset) to a portfolio."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    asset = crud.get_asset(db, data.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset {data.asset_id} not found")
    
    try:
        project = crud.add_project_to_portfolio(
            db, portfolio_id, data.asset_id, data.snapshot_id
        )
        return {
            "portfolio_project_id": project.id,
            "asset_id": project.asset_id,
            "snapshot_id": project.snapshot_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Asset {data.asset_id} already in portfolio {portfolio_id}",
        )


@router.delete("/{portfolio_id}/projects/{asset_id}", status_code=200)
def remove_project(portfolio_id: int, asset_id: int, db: Session = Depends(get_db)):
    """Remove a project from a portfolio."""
    project = (
        db.query(PortfolioProject)
        .filter(
            PortfolioProject.portfolio_id == portfolio_id,
            PortfolioProject.asset_id == asset_id,
        )
        .first()
    )
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project (asset {asset_id}) not found in portfolio {portfolio_id}",
        )
    db.delete(project)
    db.commit()
    return {"detail": f"Project (asset {asset_id}) removed from portfolio {portfolio_id}"}


@router.put("/{portfolio_id}/projects/{asset_id}/deactivate", status_code=200)
def deactivate_project(portfolio_id: int, asset_id: int, db: Session = Depends(get_db)):
    """
    Deactivate (kill) a project in a portfolio.
    Auto-creates a project_kill override (v5).
    """
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    if portfolio.portfolio_type == "base":
        raise HTTPException(status_code=400, detail="Cannot deactivate projects in a base portfolio")
    
    project = crud.deactivate_project(db, portfolio_id, asset_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project (asset {asset_id}) not found in portfolio {portfolio_id}",
        )
    return {"detail": f"Project (asset {asset_id}) deactivated", "is_active": False}


@router.put("/{portfolio_id}/projects/{asset_id}/activate", status_code=200)
def activate_project(portfolio_id: int, asset_id: int, db: Session = Depends(get_db)):
    """
    Reactivate a previously deactivated project.
    Deletes the project_kill override (v5).
    """
    project = crud.activate_project(db, portfolio_id, asset_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project (asset {asset_id}) not found in portfolio {portfolio_id}",
        )
    return {"detail": f"Project (asset {asset_id}) reactivated", "is_active": True}


# ---------------------------------------------------------------------------
# OVERRIDES
# ---------------------------------------------------------------------------

@router.post("/{portfolio_id}/overrides", status_code=201)
def add_override(portfolio_id: int, data: OverrideCreate, db: Session = Depends(get_db)):
    """Add a scenario override to a portfolio project."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    if portfolio.portfolio_type == "base":
        raise HTTPException(status_code=400, detail="Cannot add overrides to a base portfolio")
    
    # Verify the portfolio_project belongs to this portfolio
    project = (
        db.query(PortfolioProject)
        .filter(PortfolioProject.id == data.portfolio_project_id)
        .first()
    )
    if not project or project.portfolio_id != portfolio_id:
        raise HTTPException(
            status_code=404,
            detail=f"Portfolio project {data.portfolio_project_id} not found in portfolio {portfolio_id}",
        )
    
    override = crud.add_override(db, data)
    return {
        "override_id": override.id,
        "override_type": override.override_type,
        "override_value": override.override_value,
    }


@router.delete("/{portfolio_id}/overrides/{override_id}", status_code=200)
def remove_override(portfolio_id: int, override_id: int, db: Session = Depends(get_db)):
    """Remove a scenario override."""
    deleted = crud.delete_override(db, override_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Override {override_id} not found")
    return {"detail": f"Override {override_id} removed"}


# ---------------------------------------------------------------------------
# HYPOTHETICAL PROJECTS
# ---------------------------------------------------------------------------

@router.post("/{portfolio_id}/added-projects", status_code=201)
def add_hypothetical_project(
    portfolio_id: int, data: AddedProjectCreate, db: Session = Depends(get_db)
):
    """
    Add a hypothetical project to a portfolio.
    Auto-creates a project_add override (v5).
    """
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    added = crud.add_hypothetical_project(db, portfolio_id, data)
    return {"id": added.id, "compound_name": added.compound_name}


# ---------------------------------------------------------------------------
# BD PLACEHOLDERS
# ---------------------------------------------------------------------------

@router.post("/{portfolio_id}/bd-placeholders", status_code=201)
def add_bd_placeholder(
    portfolio_id: int, data: BDPlaceholderCreate, db: Session = Depends(get_db)
):
    """
    Add a BD placeholder to a portfolio.
    Auto-creates a bd_add override (v5).
    """
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    bd = crud.add_bd_placeholder(db, portfolio_id, data)
    return {"id": bd.id, "deal_name": bd.deal_name}


@router.delete("/{portfolio_id}/bd-placeholders/{bd_id}", status_code=200)
def remove_bd_placeholder(portfolio_id: int, bd_id: int, db: Session = Depends(get_db)):
    """Remove a BD placeholder from a portfolio."""
    bd = (
        db.query(PortfolioBDPlaceholder)
        .filter(
            PortfolioBDPlaceholder.id == bd_id,
            PortfolioBDPlaceholder.portfolio_id == portfolio_id,
        )
        .first()
    )
    if not bd:
        raise HTTPException(status_code=404, detail=f"BD placeholder {bd_id} not found")
    
    # v5: Delete corresponding bd_add override
    db.query(PortfolioScenarioOverride).filter(
        PortfolioScenarioOverride.override_type == "bd_add",
        PortfolioScenarioOverride.override_value == float(bd_id),
    ).delete()
    
    db.delete(bd)
    db.commit()
    return {"detail": f"BD placeholder {bd_id} removed"}


# ---------------------------------------------------------------------------
# PORTFOLIO SIMULATION
# ---------------------------------------------------------------------------

@router.post("/{portfolio_id}/simulate")
def simulate_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    """
    Run portfolio simulation. Calculates NPV for all projects,
    applies overrides, and aggregates portfolio totals.
    """
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    try:
        from ..engines.portfolio_sim import simulate_portfolio as sim_engine
        result = sim_engine(portfolio_id, db)
        return result
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Portfolio simulation engine not yet implemented (Phase F)",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# SIMULATION RUNS (v5)
# ---------------------------------------------------------------------------

@router.post("/{portfolio_id}/runs", status_code=201)
def save_simulation_run(
    portfolio_id: int, data: SimulationRunCreate, db: Session = Depends(get_db)
):
    """
    Save current portfolio simulation state as a named run.
    Requires that simulation has been run (portfolio_results exist).
    """
    try:
        run = crud.save_simulation_run(db, portfolio_id, data)
        return {
            "run_id": run.id,
            "run_name": run.run_name,
            "total_npv": run.total_npv,
            "timestamp": run.run_timestamp.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Run name '{data.run_name}' already exists for this portfolio",
        )


@router.get("/{portfolio_id}/runs")
def list_simulation_runs(portfolio_id: int, db: Session = Depends(get_db)):
    """List all saved simulation runs for a portfolio, newest first."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
    
    runs = crud.list_simulation_runs(db, portfolio_id)
    return [
        {
            "run_id": r.id, "run_name": r.run_name,
            "total_npv": r.total_npv,
            "run_timestamp": r.run_timestamp.isoformat(),
            "notes": r.notes,
            "overrides_count": len(json.loads(r.overrides_snapshot_json)) if r.overrides_snapshot_json else 0,
        }
        for r in runs
    ]


@router.get("/{portfolio_id}/runs/{run_id}")
def get_simulation_run_detail(
    portfolio_id: int, run_id: int, db: Session = Depends(get_db)
):
    """Get full detail of a saved simulation run including frozen data."""
    run = crud.get_simulation_run(db, run_id)
    if not run or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    return {
        "run_id": run.id,
        "run_name": run.run_name,
        "portfolio_id": run.portfolio_id,
        "total_npv": run.total_npv,
        "run_timestamp": run.run_timestamp.isoformat(),
        "notes": run.notes,
        "total_rd_cost_json": run.total_rd_cost_json,
        "total_sales_json": run.total_sales_json,
        "overrides": json.loads(run.overrides_snapshot_json),
        "results": json.loads(run.results_snapshot_json),
        "added_projects": json.loads(run.added_projects_snapshot_json) if run.added_projects_snapshot_json else [],
        "bd_placeholders": json.loads(run.bd_placeholders_snapshot_json) if run.bd_placeholders_snapshot_json else [],
        "deactivated_assets": json.loads(run.deactivated_assets_json) if run.deactivated_assets_json else [],
        "simulation_families_used": run.simulation_families_used,
    }


@router.delete("/{portfolio_id}/runs/{run_id}", status_code=200)
def delete_simulation_run(
    portfolio_id: int, run_id: int, db: Session = Depends(get_db)
):
    """Delete a saved simulation run."""
    deleted = crud.delete_simulation_run(db, run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {"detail": f"Run {run_id} deleted"}


@router.put("/{portfolio_id}/runs/{run_id}")
def update_simulation_run(
    portfolio_id: int, run_id: int, data: SimulationRunUpdate,
    db: Session = Depends(get_db),
):
    """Update a simulation run's metadata (name, notes)."""
    run = crud.update_simulation_run(db, run_id, data)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {"run_id": run.id, "run_name": run.run_name, "notes": run.notes}


@router.post("/{portfolio_id}/runs/{run_id}/restore")
def restore_simulation_run(
    portfolio_id: int, run_id: int, db: Session = Depends(get_db)
):
    """
    Restore overrides from a saved simulation run as the current working state.
    The saved run itself is unchanged (immutable). Only the current mutable state
    is replaced with the frozen data from the run.
    """
    run = crud.get_simulation_run(db, run_id)
    if not run or run.portfolio_id != portfolio_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    try:
        from ..engines.portfolio_sim import restore_simulation_run as restore_engine
        result = restore_engine(portfolio_id, run_id, db)
        return result
    except ImportError:
        # Manual restore without re-simulation (Phase F will add engine)
        # For now, just restore the overrides
        overrides_data = json.loads(run.overrides_snapshot_json)
        
        # Clear current overrides
        portfolio = crud.get_portfolio(db, portfolio_id)
        for proj in portfolio.projects:
            db.query(PortfolioScenarioOverride).filter(
                PortfolioScenarioOverride.portfolio_project_id == proj.id
            ).delete()
            proj.is_active = True  # Reset all to active
        
        # Restore deactivated flags
        deactivated = json.loads(run.deactivated_assets_json) if run.deactivated_assets_json else []
        for proj in portfolio.projects:
            if proj.asset_id in deactivated:
                proj.is_active = False
        
        # Restore overrides
        for ov_data in overrides_data:
            # Find the portfolio_project by asset_id
            proj = (
                db.query(PortfolioProject)
                .filter(
                    PortfolioProject.portfolio_id == portfolio_id,
                    PortfolioProject.asset_id == ov_data.get("asset_id"),
                )
                .first()
            )
            if proj:
                db.add(PortfolioScenarioOverride(
                    portfolio_project_id=proj.id,
                    override_type=ov_data["override_type"],
                    phase_name=ov_data.get("phase_name"),
                    override_value=ov_data["override_value"],
                    description=ov_data.get("description"),
                ))
        
        db.commit()
        return {
            "restored": True,
            "overrides_count": len(overrides_data),
            "note": "Overrides restored. Run simulation to refresh results.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


