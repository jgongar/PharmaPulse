"""
PharmaPulse CRUD Operations

Database access functions for all tables. These functions encapsulate
all SQLAlchemy queries and are called by API routers.

Architecture:
    - Each function takes a db: Session parameter (injected by FastAPI)
    - Functions return ORM model instances (routers convert to Pydantic)
    - Create functions return the created instance
    - Get functions return None if not found (routers raise 404)
    - List functions return lists (empty list if none found)

Naming convention:
    - create_xxx: INSERT new record
    - get_xxx: SELECT single record by ID
    - list_xxx: SELECT multiple records with optional filters
    - update_xxx: UPDATE existing record
    - delete_xxx: DELETE record (CASCADE handles children)
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .models import (
    Asset, Snapshot, PhaseInput, RDCost, CommercialRow,
    MCCommercialConfig, MCRDConfig, WhatIfPhaseLever, Cashflow,
    Portfolio, PortfolioProject, PortfolioScenarioOverride,
    PortfolioResult, PortfolioAddedProject, PortfolioBDPlaceholder,
    PortfolioSimulationRun
)
from .schemas import (
    AssetCreate, AssetUpdate, SnapshotCreate,
    PortfolioCreate, OverrideCreate, AddedProjectCreate,
    BDPlaceholderCreate, SimulationRunCreate, SimulationRunUpdate
)


# ---------------------------------------------------------------------------
# ASSET CRUD
# ---------------------------------------------------------------------------

def create_asset(db: Session, data: AssetCreate) -> Asset:
    """
    Create a new drug asset in the database.
    
    Args:
        db: Database session
        data: Validated asset creation data
        
    Returns:
        The created Asset ORM instance
        
    Raises:
        IntegrityError: If (sponsor, compound_name, indication) already exists
    """
    asset = Asset(**data.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def get_asset(db: Session, asset_id: int) -> Optional[Asset]:
    """Get a single asset by ID. Returns None if not found."""
    return db.query(Asset).filter(Asset.id == asset_id).first()


def list_assets(
    db: Session,
    is_internal: Optional[bool] = None,
    therapeutic_area: Optional[str] = None,
    compound_name: Optional[str] = None,
    current_phase: Optional[str] = None,
    min_npv: Optional[float] = None,
    max_npv: Optional[float] = None,
) -> list[Asset]:
    """
    List assets with optional filters.
    
    Filters:
        is_internal: True for internal, False for competitor
        therapeutic_area: Exact match on TA
        compound_name: Partial match (LIKE) on compound name
        current_phase: Exact match on phase
        min_npv / max_npv: Range filter on npv_deterministic
    """
    query = db.query(Asset)
    
    if is_internal is not None:
        query = query.filter(Asset.is_internal == is_internal)
    if therapeutic_area:
        query = query.filter(Asset.therapeutic_area == therapeutic_area)
    if compound_name:
        query = query.filter(Asset.compound_name.ilike(f"%{compound_name}%"))
    if current_phase:
        query = query.filter(Asset.current_phase == current_phase)
    if min_npv is not None:
        query = query.filter(Asset.npv_deterministic >= min_npv)
    if max_npv is not None:
        query = query.filter(Asset.npv_deterministic <= max_npv)
    
    return query.order_by(Asset.id).all()


def update_asset(db: Session, asset_id: int, data: AssetUpdate) -> Optional[Asset]:
    """Update an existing asset. Only non-None fields are updated."""
    asset = get_asset(db, asset_id)
    if not asset:
        return None
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            setattr(asset, field, value)
    
    asset.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, asset_id: int) -> bool:
    """Delete an asset and all its snapshots (CASCADE). Returns True if deleted."""
    asset = get_asset(db, asset_id)
    if not asset:
        return False
    db.delete(asset)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# SNAPSHOT CRUD
# ---------------------------------------------------------------------------

def create_snapshot(db: Session, asset_id: int, data: SnapshotCreate) -> Snapshot:
    """
    Create a new snapshot with all child data (phases, costs, commercial, MC config).
    This is a complex operation that inserts into multiple tables atomically.
    """
    # Create the snapshot record
    snapshot = Snapshot(
        asset_id=asset_id,
        snapshot_name=data.snapshot_name,
        description=data.description,
        valuation_year=data.valuation_year,
        horizon_years=data.horizon_years,
        wacc_rd=data.wacc_rd,
        approval_date=data.approval_date,
        mc_iterations=data.mc_iterations,
        random_seed=data.random_seed,
        whatif_revenue_lever=data.whatif_revenue_lever,
        whatif_rd_cost_lever=data.whatif_rd_cost_lever,
    )
    db.add(snapshot)
    db.flush()  # Get the snapshot.id without committing

    # Add phase inputs
    for pi in data.phase_inputs:
        db.add(PhaseInput(
            snapshot_id=snapshot.id,
            phase_name=pi.phase_name,
            start_date=pi.start_date,
            success_rate=pi.success_rate,
        ))

    # Add R&D costs
    for rc in data.rd_costs:
        db.add(RDCost(
            snapshot_id=snapshot.id,
            year=rc.year,
            phase_name=rc.phase_name,
            rd_cost=rc.rd_cost,
        ))

    # Add commercial rows
    for cr in data.commercial_rows:
        db.add(CommercialRow(
            snapshot_id=snapshot.id,
            **cr.model_dump(),
        ))

    # Add MC commercial config (optional)
    if data.mc_commercial_config:
        db.add(MCCommercialConfig(
            snapshot_id=snapshot.id,
            **data.mc_commercial_config.model_dump(),
        ))

    # Add MC R&D configs (optional)
    if data.mc_rd_configs:
        for mc in data.mc_rd_configs:
            db.add(MCRDConfig(
                snapshot_id=snapshot.id,
                **mc.model_dump(),
            ))

    # Add what-if phase levers (optional)
    if data.whatif_phase_levers:
        for wl in data.whatif_phase_levers:
            db.add(WhatIfPhaseLever(
                snapshot_id=snapshot.id,
                **wl.model_dump(),
            ))

    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_snapshot(db: Session, snapshot_id: int) -> Optional[Snapshot]:
    """Get a snapshot by ID with all relationships eagerly loaded."""
    return (
        db.query(Snapshot)
        .options(
            joinedload(Snapshot.phase_inputs),
            joinedload(Snapshot.rd_costs),
            joinedload(Snapshot.commercial_rows),
            joinedload(Snapshot.mc_commercial_config),
            joinedload(Snapshot.mc_rd_configs),
            joinedload(Snapshot.whatif_phase_levers),
        )
        .filter(Snapshot.id == snapshot_id)
        .first()
    )


def list_snapshots(db: Session, asset_id: int) -> list[Snapshot]:
    """List all snapshots for an asset."""
    return (
        db.query(Snapshot)
        .filter(Snapshot.asset_id == asset_id)
        .order_by(Snapshot.created_at.desc())
        .all()
    )


def clone_snapshot(db: Session, asset_id: int, snapshot_id: int, new_name: str) -> Snapshot:
    """
    Deep-clone a snapshot with all child data.
    
    CRITICAL: Copies ALL child data independently:
    - phase_inputs, rd_costs, commercial_rows
    - mc_commercial_config, mc_rd_configs, whatif_phase_levers
    - Cashflows are NOT copied (results cleared, will be recalculated)
    - NPV results are cleared (set to NULL)
    """
    original = get_snapshot(db, snapshot_id)
    if not original or original.asset_id != asset_id:
        return None

    # Create new snapshot record (clear results)
    new_snapshot = Snapshot(
        asset_id=asset_id,
        snapshot_name=new_name,
        description=f"Clone of '{original.snapshot_name}'",
        valuation_year=original.valuation_year,
        horizon_years=original.horizon_years,
        wacc_rd=original.wacc_rd,
        approval_date=original.approval_date,
        mc_iterations=original.mc_iterations,
        random_seed=original.random_seed,
        whatif_revenue_lever=original.whatif_revenue_lever,
        whatif_rd_cost_lever=original.whatif_rd_cost_lever,
        # Results cleared — will be recalculated
        npv_deterministic=None,
        npv_deterministic_whatif=None,
        npv_mc_average=None,
    )
    db.add(new_snapshot)
    db.flush()

    # Copy phase inputs
    for pi in original.phase_inputs:
        db.add(PhaseInput(
            snapshot_id=new_snapshot.id,
            phase_name=pi.phase_name,
            start_date=pi.start_date,
            success_rate=pi.success_rate,
        ))

    # Copy R&D costs
    for rc in original.rd_costs:
        db.add(RDCost(
            snapshot_id=new_snapshot.id,
            year=rc.year,
            phase_name=rc.phase_name,
            rd_cost=rc.rd_cost,
        ))

    # Copy commercial rows
    for cr in original.commercial_rows:
        new_cr = CommercialRow(snapshot_id=new_snapshot.id)
        for col in CommercialRow.__table__.columns:
            if col.name not in ("id", "snapshot_id"):
                setattr(new_cr, col.name, getattr(cr, col.name))
        db.add(new_cr)

    # Copy MC commercial config
    if original.mc_commercial_config:
        new_mc = MCCommercialConfig(snapshot_id=new_snapshot.id)
        for col in MCCommercialConfig.__table__.columns:
            if col.name not in ("id", "snapshot_id"):
                setattr(new_mc, col.name, getattr(original.mc_commercial_config, col.name))
        db.add(new_mc)

    # Copy MC R&D configs
    for mc in original.mc_rd_configs:
        db.add(MCRDConfig(
            snapshot_id=new_snapshot.id,
            phase_name=mc.phase_name,
            variable=mc.variable,
            toggle=mc.toggle,
            min_value=mc.min_value,
            min_probability=mc.min_probability,
            max_value=mc.max_value,
            max_probability=mc.max_probability,
        ))

    # Copy what-if phase levers
    for wl in original.whatif_phase_levers:
        db.add(WhatIfPhaseLever(
            snapshot_id=new_snapshot.id,
            phase_name=wl.phase_name,
            lever_sr=wl.lever_sr,
            lever_duration_months=wl.lever_duration_months,
        ))

    # NOTE: Cashflows are NOT copied — results are cleared

    db.commit()
    db.refresh(new_snapshot)
    return new_snapshot


# ---------------------------------------------------------------------------
# PORTFOLIO CRUD
# ---------------------------------------------------------------------------

def create_portfolio(db: Session, data: PortfolioCreate) -> Portfolio:
    """
    Create a new portfolio. If asset_ids provided (v5), bulk-add projects.
    
    Returns the created portfolio with projects if applicable.
    Raises ValueError if any asset_id is not found.
    """
    portfolio = Portfolio(
        portfolio_name=data.portfolio_name,
        description=data.description,
        portfolio_type=data.portfolio_type,
        base_portfolio_id=data.base_portfolio_id,
    )
    db.add(portfolio)
    db.flush()

    # v5: Bulk-add projects at creation if asset_ids provided
    if data.asset_ids:
        missing = []
        for aid in data.asset_ids:
            asset = db.query(Asset).filter(Asset.id == aid).first()
            if not asset:
                missing.append(aid)
                continue
            # Find the latest snapshot for this asset
            latest_snapshot = (
                db.query(Snapshot)
                .filter(Snapshot.asset_id == aid)
                .order_by(Snapshot.created_at.desc())
                .first()
            )
            if latest_snapshot:
                db.add(PortfolioProject(
                    portfolio_id=portfolio.id,
                    asset_id=aid,
                    snapshot_id=latest_snapshot.id,
                    is_active=True,
                ))
        if missing:
            db.rollback()
            raise ValueError(f"Asset IDs not found: {missing}")

    db.commit()
    db.refresh(portfolio)
    return portfolio


def get_portfolio(db: Session, portfolio_id: int) -> Optional[Portfolio]:
    """Get a portfolio by ID with all relationships."""
    return (
        db.query(Portfolio)
        .options(
            joinedload(Portfolio.projects).joinedload(PortfolioProject.asset),
            joinedload(Portfolio.projects).joinedload(PortfolioProject.snapshot),
            joinedload(Portfolio.projects).joinedload(PortfolioProject.overrides),
            joinedload(Portfolio.added_projects),
            joinedload(Portfolio.bd_placeholders),
            joinedload(Portfolio.simulation_runs),
        )
        .filter(Portfolio.id == portfolio_id)
        .first()
    )


def list_portfolios(db: Session) -> list[dict]:
    """
    List all portfolios with project count, saved runs count, and latest run info (v5).
    Returns a list of dicts ready for API response.
    """
    portfolios = db.query(Portfolio).order_by(Portfolio.id).all()
    result = []
    for p in portfolios:
        project_count = (
            db.query(func.count(PortfolioProject.id))
            .filter(PortfolioProject.portfolio_id == p.id)
            .scalar()
        )
        runs_count = (
            db.query(func.count(PortfolioSimulationRun.id))
            .filter(PortfolioSimulationRun.portfolio_id == p.id)
            .scalar()
        )
        latest_run = (
            db.query(PortfolioSimulationRun)
            .filter(PortfolioSimulationRun.portfolio_id == p.id)
            .order_by(PortfolioSimulationRun.run_timestamp.desc())
            .first()
        )
        latest_run_dict = None
        if latest_run:
            latest_run_dict = {
                "run_id": latest_run.id,
                "run_name": latest_run.run_name,
                "total_npv": latest_run.total_npv,
                "run_timestamp": latest_run.run_timestamp.isoformat(),
            }
        result.append({
            "id": p.id,
            "portfolio_name": p.portfolio_name,
            "portfolio_type": p.portfolio_type,
            "base_portfolio_id": p.base_portfolio_id,
            "total_npv": p.total_npv,
            "created_at": p.created_at.isoformat(),
            "project_count": project_count,
            "saved_runs_count": runs_count,
            "latest_run": latest_run_dict,
        })
    return result


def add_project_to_portfolio(
    db: Session, portfolio_id: int, asset_id: int, snapshot_id: Optional[int] = None
) -> PortfolioProject:
    """
    Add a project to a portfolio. If snapshot_id not specified, uses the latest.
    """
    if not snapshot_id:
        snapshot = (
            db.query(Snapshot)
            .filter(Snapshot.asset_id == asset_id)
            .order_by(Snapshot.created_at.desc())
            .first()
        )
        if not snapshot:
            raise ValueError(f"No snapshots found for asset {asset_id}")
        snapshot_id = snapshot.id

    project = PortfolioProject(
        portfolio_id=portfolio_id,
        asset_id=asset_id,
        snapshot_id=snapshot_id,
        is_active=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def deactivate_project(db: Session, portfolio_id: int, asset_id: int) -> PortfolioProject:
    """
    Deactivate a project in a portfolio (set is_active=False).
    Auto-creates a project_kill override (v5).
    """
    project = (
        db.query(PortfolioProject)
        .filter(
            PortfolioProject.portfolio_id == portfolio_id,
            PortfolioProject.asset_id == asset_id,
        )
        .first()
    )
    if not project:
        return None
    
    project.is_active = False
    
    # v5: Auto-create project_kill override
    existing_kill = (
        db.query(PortfolioScenarioOverride)
        .filter(
            PortfolioScenarioOverride.portfolio_project_id == project.id,
            PortfolioScenarioOverride.override_type == "project_kill",
        )
        .first()
    )
    if not existing_kill:
        db.add(PortfolioScenarioOverride(
            portfolio_project_id=project.id,
            override_type="project_kill",
            override_value=1.0,
            description="Project killed/deactivated",
        ))
    
    db.commit()
    db.refresh(project)
    return project


def activate_project(db: Session, portfolio_id: int, asset_id: int) -> PortfolioProject:
    """
    Reactivate a project in a portfolio (set is_active=True).
    Deletes the project_kill override (v5).
    """
    project = (
        db.query(PortfolioProject)
        .filter(
            PortfolioProject.portfolio_id == portfolio_id,
            PortfolioProject.asset_id == asset_id,
        )
        .first()
    )
    if not project:
        return None
    
    project.is_active = True
    
    # v5: Delete project_kill override
    db.query(PortfolioScenarioOverride).filter(
        PortfolioScenarioOverride.portfolio_project_id == project.id,
        PortfolioScenarioOverride.override_type == "project_kill",
    ).delete()
    
    db.commit()
    db.refresh(project)
    return project


def add_override(db: Session, data: OverrideCreate) -> PortfolioScenarioOverride:
    """Add a scenario override to a portfolio project."""
    override = PortfolioScenarioOverride(
        portfolio_project_id=data.portfolio_project_id,
        override_type=data.override_type,
        phase_name=data.phase_name,
        override_value=data.override_value,
        acceleration_budget_multiplier=data.acceleration_budget_multiplier,
        description=data.description,
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    return override


def delete_override(db: Session, override_id: int) -> bool:
    """Delete a scenario override. Returns True if deleted."""
    override = (
        db.query(PortfolioScenarioOverride)
        .filter(PortfolioScenarioOverride.id == override_id)
        .first()
    )
    if not override:
        return False
    db.delete(override)
    db.commit()
    return True


def add_hypothetical_project(
    db: Session, portfolio_id: int, data: AddedProjectCreate
) -> PortfolioAddedProject:
    """
    Add a hypothetical project to a portfolio.
    Auto-creates a project_add override via the first portfolio_project (v5).
    """
    added = PortfolioAddedProject(
        portfolio_id=portfolio_id,
        **data.model_dump(),
    )
    db.add(added)
    db.flush()

    # v5: Auto-create project_add override
    # Link to the first project in the portfolio (as a reference point)
    first_project = (
        db.query(PortfolioProject)
        .filter(PortfolioProject.portfolio_id == portfolio_id)
        .first()
    )
    if first_project:
        db.add(PortfolioScenarioOverride(
            portfolio_project_id=first_project.id,
            override_type="project_add",
            override_value=float(added.id),
            description=f"Added hypothetical project: {data.compound_name}",
        ))

    db.commit()
    db.refresh(added)
    return added


def add_bd_placeholder(
    db: Session, portfolio_id: int, data: BDPlaceholderCreate
) -> PortfolioBDPlaceholder:
    """
    Add a BD placeholder to a portfolio.
    Auto-creates a bd_add override (v5).
    """
    bd = PortfolioBDPlaceholder(
        portfolio_id=portfolio_id,
        **data.model_dump(),
    )
    db.add(bd)
    db.flush()

    # v5: Auto-create bd_add override
    first_project = (
        db.query(PortfolioProject)
        .filter(PortfolioProject.portfolio_id == portfolio_id)
        .first()
    )
    if first_project:
        db.add(PortfolioScenarioOverride(
            portfolio_project_id=first_project.id,
            override_type="bd_add",
            override_value=float(bd.id),
            description=f"Added BD deal: {data.deal_name}",
        ))

    db.commit()
    db.refresh(bd)
    return bd


def delete_portfolio(db: Session, portfolio_id: int) -> bool:
    """Delete a portfolio and all child data (CASCADE). Returns True if deleted."""
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        return False
    db.delete(portfolio)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# SIMULATION RUN CRUD (v5)
# ---------------------------------------------------------------------------

def save_simulation_run(
    db: Session, portfolio_id: int, data: SimulationRunCreate
) -> PortfolioSimulationRun:
    """
    Save current portfolio simulation state as a frozen named run.
    Requires that portfolio_results exist (simulation has been run).
    """
    portfolio = get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError("Portfolio not found")
    
    # Check simulation has been run
    results = (
        db.query(PortfolioResult)
        .filter(PortfolioResult.portfolio_id == portfolio_id)
        .all()
    )
    if not results:
        raise ValueError("No simulation results exist. Run simulation first.")
    
    # Collect current state for freezing
    # Overrides
    overrides = []
    for proj in portfolio.projects:
        for ov in proj.overrides:
            overrides.append({
                "portfolio_project_id": ov.portfolio_project_id,
                "asset_id": proj.asset_id,
                "compound_name": proj.asset.compound_name,
                "override_type": ov.override_type,
                "phase_name": ov.phase_name,
                "override_value": ov.override_value,
                "description": ov.description,
            })
    
    # Results
    results_data = []
    for r in results:
        results_data.append({
            "asset_id": r.asset_id,
            "compound_name": r.compound_name,
            "is_active": r.is_active,
            "npv_original": r.npv_original,
            "npv_simulated": r.npv_simulated,
            "npv_used": r.npv_used,
        })
    
    # Added projects
    added = [
        {
            "id": ap.id,
            "compound_name": ap.compound_name,
            "peak_sales": ap.peak_sales,
            "npv_calculated": ap.npv_calculated,
        }
        for ap in portfolio.added_projects
    ]
    
    # BD placeholders
    bds = [
        {
            "id": bd.id,
            "deal_name": bd.deal_name,
            "deal_type": bd.deal_type,
            "npv_calculated": bd.npv_calculated,
        }
        for bd in portfolio.bd_placeholders
    ]
    
    # Deactivated assets
    deactivated = [
        proj.asset_id for proj in portfolio.projects if not proj.is_active
    ]
    
    run = PortfolioSimulationRun(
        portfolio_id=portfolio_id,
        run_name=data.run_name,
        total_npv=portfolio.total_npv or 0,
        total_rd_cost_json=portfolio.total_rd_cost_json,
        total_sales_json=portfolio.total_sales_json,
        overrides_snapshot_json=json.dumps(overrides),
        results_snapshot_json=json.dumps(results_data),
        added_projects_snapshot_json=json.dumps(added) if added else None,
        bd_placeholders_snapshot_json=json.dumps(bds) if bds else None,
        deactivated_assets_json=json.dumps(deactivated) if deactivated else None,
        notes=data.notes,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_simulation_runs(db: Session, portfolio_id: int) -> list[PortfolioSimulationRun]:
    """List all saved simulation runs for a portfolio, newest first."""
    return (
        db.query(PortfolioSimulationRun)
        .filter(PortfolioSimulationRun.portfolio_id == portfolio_id)
        .order_by(PortfolioSimulationRun.run_timestamp.desc())
        .all()
    )


def get_simulation_run(db: Session, run_id: int) -> Optional[PortfolioSimulationRun]:
    """Get a single simulation run by ID."""
    return (
        db.query(PortfolioSimulationRun)
        .filter(PortfolioSimulationRun.id == run_id)
        .first()
    )


def delete_simulation_run(db: Session, run_id: int) -> bool:
    """Delete a simulation run. Returns True if deleted."""
    run = get_simulation_run(db, run_id)
    if not run:
        return False
    db.delete(run)
    db.commit()
    return True


def update_simulation_run(
    db: Session, run_id: int, data: SimulationRunUpdate
) -> Optional[PortfolioSimulationRun]:
    """Update a simulation run's metadata (name, notes)."""
    run = get_simulation_run(db, run_id)
    if not run:
        return None
    if data.run_name is not None:
        run.run_name = data.run_name
    if data.notes is not None:
        run.notes = data.notes
    db.commit()
    db.refresh(run)
    return run


