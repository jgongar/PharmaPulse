"""
PharmaPulse — Portfolio Simulation Engine

Calculates NPV for all active projects in a portfolio, applies scenario
overrides, aggregates totals, and supports hypothetical projects / BD placeholders.

Workflow:
    1. Load portfolio with all projects, overrides, added projects, BD placeholders
    2. For each active project:
       a. Read its snapshot's deterministic NPV (already calculated)
       b. Apply any scenario overrides (phase_delay, peak_sales_change, sr_override, etc.)
       c. Record original vs simulated NPV
    3. Add NPV contributions from hypothetical projects and BD placeholders
    4. Aggregate portfolio total NPV and yearly cashflows
    5. Store results in portfolio_results table (ephemeral, overwritten each run)
    6. Update portfolio totals

Override types and their effects:
    - phase_delay:          Shift all commercial cashflows by N months
    - peak_sales_change:    Multiply peak revenue by (1 + override_value/100)
    - sr_override:          Replace success rate for a specific phase
    - launch_delay:         Shift launch date by N months
    - time_to_peak_change:  Adjust time-to-peak by N years
    - accelerate:           Reduce phase duration, increase R&D cost
    - budget_realloc:       Multiply R&D cost for a phase
    - project_kill:         Set NPV to 0 (project deactivated)
    - project_add:          Reference to PortfolioAddedProject
    - bd_add:               Reference to PortfolioBDPlaceholder
"""

import json
import math
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    Portfolio, PortfolioProject, PortfolioScenarioOverride,
    PortfolioResult, PortfolioAddedProject, PortfolioBDPlaceholder,
    Asset, Snapshot, Cashflow,
)
from .. import crud
from .deterministic import calculate_deterministic_npv


def simulate_override_npv(
    snapshot: "Snapshot",
    db: Session,
    *,
    peak_sales_pct_change: float | None = None,
    sr_override_phase: str | None = None,
    sr_override_value: float | None = None,
    phase_delay_months: float | None = None,
    launch_delay_months: float | None = None,
    time_to_peak_change_years: float | None = None,
    duration_shift: dict | None = None,
    rd_cost_multiplier: float | None = None,
) -> float:
    """
    Compute exact NPV by cloning a snapshot, applying modifications,
    and running the deterministic engine on the clone.

    Returns the computed NPV. Temp snapshot is deleted in finally block.
    """
    asset = db.query(Asset).filter(Asset.id == snapshot.asset_id).first()

    # Clean up any stale temp snapshots for this asset
    from ..models import Snapshot as SnapshotModel
    db.query(SnapshotModel).filter(
        SnapshotModel.asset_id == snapshot.asset_id,
        SnapshotModel.snapshot_name.like("__temp_%"),
    ).delete(synchronize_session="fetch")
    db.flush()

    temp_name = f"__temp_{uuid.uuid4().hex[:8]}__"
    temp_snapshot = crud.clone_snapshot(
        db, snapshot.asset_id, snapshot.id, temp_name
    )
    if not temp_snapshot:
        return snapshot.npv_deterministic or 0.0

    try:
        # Apply peak_sales_change: scale peak_sales on all commercial rows
        if peak_sales_pct_change is not None:
            multiplier = 1.0 + (peak_sales_pct_change / 100.0)
            for cr in temp_snapshot.commercial_rows:
                cr.peak_sales = (cr.peak_sales or 0) * multiplier

        # Apply SR override for a specific phase
        if sr_override_phase and sr_override_value is not None:
            for pi in temp_snapshot.phase_inputs:
                if pi.phase_name == sr_override_phase:
                    pi.success_rate = sr_override_value

        # Apply phase delay (shift all phase start dates and approval date)
        if phase_delay_months is not None:
            shift_years = phase_delay_months / 12.0
            for pi in temp_snapshot.phase_inputs:
                pi.start_date = pi.start_date + shift_years
            temp_snapshot.approval_date = (temp_snapshot.approval_date or 0) + shift_years
            for cr in temp_snapshot.commercial_rows:
                cr.launch_date = (cr.launch_date or 0) + shift_years

        # Apply launch delay (shift only commercial launch dates)
        if launch_delay_months is not None:
            shift_years = launch_delay_months / 12.0
            for cr in temp_snapshot.commercial_rows:
                cr.launch_date = (cr.launch_date or 0) + shift_years

        # Apply time_to_peak change
        if time_to_peak_change_years is not None:
            for cr in temp_snapshot.commercial_rows:
                cr.time_to_peak = max(0.5, (cr.time_to_peak or 3) + time_to_peak_change_years)

        # Apply duration shift (for acceleration — shift specific phase start dates)
        if duration_shift:
            # Use WhatIfPhaseLever mechanism: set lever_duration_months
            from ..models import WhatIfPhaseLever
            for phase_name, months in duration_shift.items():
                db.add(WhatIfPhaseLever(
                    snapshot_id=temp_snapshot.id,
                    phase_name=phase_name,
                    lever_duration_months=months,
                    lever_sr=None,
                ))

        # Apply R&D cost multiplier
        if rd_cost_multiplier is not None:
            from ..models import RDCost
            for rc in temp_snapshot.rd_costs:
                rc.rd_cost = rc.rd_cost * rd_cost_multiplier

        db.flush()

        # Run deterministic engine on cloned snapshot
        is_whatif = bool(duration_shift)
        result = calculate_deterministic_npv(temp_snapshot.id, db, is_whatif=is_whatif)
        return result["npv_deterministic"]

    finally:
        # Clean up temp snapshot (CASCADE deletes children)
        from ..models import Snapshot as SnapshotModel
        temp = db.query(SnapshotModel).filter(SnapshotModel.id == temp_snapshot.id).first()
        if temp:
            db.delete(temp)
            db.flush()


def simulate_portfolio(portfolio_id: int, db: Session) -> dict:
    """
    Run portfolio simulation: compute NPV for all projects,
    apply overrides, aggregate totals.
    
    Returns a dict with:
        - portfolio_id, portfolio_name
        - total_npv
        - project_results: list of per-project results
        - added_project_results: list of hypothetical project results
        - bd_placeholder_results: list of BD placeholder results
        - total_rd_cost_by_year: yearly R&D cost aggregation
        - total_sales_by_year: yearly sales aggregation
    """
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")
    
    # Clear existing ephemeral results
    db.query(PortfolioResult).filter(
        PortfolioResult.portfolio_id == portfolio_id
    ).delete()
    db.flush()
    
    project_results = []
    total_npv = 0.0
    total_rd_by_year = {}
    total_sales_by_year = {}
    
    # ---- Process each project in the portfolio ----
    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot
        
        if not snapshot:
            continue
        
        # Original NPV from snapshot
        npv_original = snapshot.npv_deterministic or 0.0
        
        # Start with original NPV
        npv_simulated = npv_original
        is_active = proj.is_active
        
        # Collect overrides for this project
        overrides_applied = []
        
        for ov in proj.overrides:
            override_effect = apply_override(
                ov, snapshot, npv_simulated, db
            )
            npv_simulated = override_effect["npv_after"]
            is_active = override_effect.get("is_active", is_active)
            overrides_applied.append({
                "type": ov.override_type,
                "value": ov.override_value,
                "phase": ov.phase_name,
                "description": ov.description,
                "npv_impact": override_effect["npv_after"] - override_effect["npv_before"],
            })
        
        # If project killed, NPV = 0
        if not is_active:
            npv_simulated = 0.0
        
        npv_used = npv_simulated
        total_npv += npv_used
        
        # Collect R&D costs and sales from cashflows
        rd_by_year, sales_by_year = _get_cashflow_aggregates(
            snapshot.id, db, is_active
        )
        _merge_yearly(total_rd_by_year, rd_by_year)
        _merge_yearly(total_sales_by_year, sales_by_year)
        
        # Save result
        result = PortfolioResult(
            portfolio_id=portfolio_id,
            asset_id=asset.id,
            compound_name=asset.compound_name,
            is_active=is_active,
            npv_original=npv_original,
            npv_simulated=npv_simulated,
            npv_used=npv_used,
            rd_cost_by_year_json=json.dumps(rd_by_year) if rd_by_year else None,
            sales_by_year_json=json.dumps(sales_by_year) if sales_by_year else None,
            overrides_applied_json=json.dumps(overrides_applied) if overrides_applied else None,
        )
        db.add(result)
        
        project_results.append({
            "asset_id": asset.id,
            "compound_name": asset.compound_name,
            "is_active": is_active,
            "npv_original": npv_original,
            "npv_simulated": npv_simulated,
            "npv_used": npv_used,
            "overrides_count": len(overrides_applied),
        })
    
    # Determine valuation_year from first project's snapshot
    _portfolio_valuation_year = 2025
    for proj in portfolio.projects:
        if proj.snapshot and proj.snapshot.valuation_year:
            _portfolio_valuation_year = proj.snapshot.valuation_year
            break

    # ---- Process added (hypothetical) projects ----
    added_results = []
    for ap in portfolio.added_projects:
        ap_npv = _calculate_added_project_npv(ap, _portfolio_valuation_year, db)
        ap.npv_calculated = ap_npv
        total_npv += ap_npv
        
        added_results.append({
            "id": ap.id,
            "compound_name": ap.compound_name,
            "npv_calculated": ap_npv,
        })
    
    # ---- Process BD placeholders ----
    bd_results = []
    for bd in portfolio.bd_placeholders:
        bd_npv = _calculate_bd_placeholder_npv(bd, _portfolio_valuation_year, db)
        bd.npv_calculated = bd_npv
        total_npv += bd_npv
        
        bd_results.append({
            "id": bd.id,
            "deal_name": bd.deal_name,
            "npv_calculated": bd_npv,
        })
    
    # ---- Update portfolio totals ----
    portfolio.total_npv = total_npv
    portfolio.total_rd_cost_json = json.dumps(total_rd_by_year) if total_rd_by_year else None
    portfolio.total_sales_json = json.dumps(total_sales_by_year) if total_sales_by_year else None
    
    db.commit()
    
    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_npv": round(total_npv, 2),
        "project_count": len(project_results),
        "active_projects": sum(1 for p in project_results if p["is_active"]),
        "project_results": project_results,
        "added_project_results": added_results,
        "bd_placeholder_results": bd_results,
        "total_rd_cost_by_year": total_rd_by_year,
        "total_sales_by_year": total_sales_by_year,
    }


def restore_simulation_run(
    portfolio_id: int, run_id: int, db: Session
) -> dict:
    """
    Restore overrides from a saved run, then re-simulate the portfolio.
    
    Steps:
    1. Load frozen overrides from the run
    2. Clear current overrides
    3. Restore saved overrides and deactivation flags
    4. Re-run portfolio simulation
    
    Returns the simulation result.
    """
    run = crud.get_simulation_run(db, run_id)
    if not run or run.portfolio_id != portfolio_id:
        raise ValueError(f"Run {run_id} not found for portfolio {portfolio_id}")
    
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")
    
    # Clear current overrides (both project-level and portfolio-level)
    for proj in portfolio.projects:
        db.query(PortfolioScenarioOverride).filter(
            PortfolioScenarioOverride.portfolio_project_id == proj.id
        ).delete()
        proj.is_active = True  # Reset all to active
    # Clear portfolio-level overrides (nullable portfolio_project_id)
    db.query(PortfolioScenarioOverride).filter(
        PortfolioScenarioOverride.portfolio_project_id.is_(None),
    ).delete()

    # Restore deactivated flags
    deactivated = json.loads(run.deactivated_assets_json) if run.deactivated_assets_json else []
    for proj in portfolio.projects:
        if proj.asset_id in deactivated:
            proj.is_active = False

    # Restore overrides
    overrides_data = json.loads(run.overrides_snapshot_json)
    for ov_data in overrides_data:
        ov_type = ov_data["override_type"]
        if ov_type in ("project_add", "bd_add"):
            # Structural overrides are portfolio-level
            db.add(PortfolioScenarioOverride(
                portfolio_project_id=None,
                reference_id=ov_data.get("reference_id"),
                override_type=ov_type,
                override_value=ov_data["override_value"],
                description=ov_data.get("description"),
            ))
        else:
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
                    override_type=ov_type,
                    phase_name=ov_data.get("phase_name"),
                    override_value=ov_data["override_value"],
                    description=ov_data.get("description"),
                ))
    
    db.flush()
    
    # Re-run simulation with restored overrides
    result = simulate_portfolio(portfolio_id, db)
    result["restored_from_run"] = run.run_name
    result["restored_overrides_count"] = len(overrides_data)
    
    return result


# ---------------------------------------------------------------------------
# OVERRIDE APPLICATION
# ---------------------------------------------------------------------------

def apply_override(
    override: PortfolioScenarioOverride,
    snapshot: Snapshot,
    current_npv: float,
    db: Session,
) -> dict:
    """
    Apply a single scenario override to a project's NPV.
    
    Returns:
        dict with keys: npv_before, npv_after, is_active
    """
    npv_before = current_npv
    npv_after = current_npv
    is_active = True
    
    otype = override.override_type
    ovalue = override.override_value
    
    if otype == "project_kill":
        # Kill project — NPV drops to 0
        npv_after = 0.0
        is_active = False

    elif otype == "peak_sales_change":
        # Use deterministic engine with modified peak sales
        npv_after = simulate_override_npv(
            snapshot, db, peak_sales_pct_change=ovalue
        )

    elif otype == "sr_override":
        # Use deterministic engine with modified success rate
        npv_after = simulate_override_npv(
            snapshot, db,
            sr_override_phase=override.phase_name,
            sr_override_value=ovalue,
        )

    elif otype == "phase_delay":
        # Use deterministic engine with shifted phase dates
        npv_after = simulate_override_npv(
            snapshot, db, phase_delay_months=ovalue
        )

    elif otype == "launch_delay":
        # Use deterministic engine with shifted launch dates
        npv_after = simulate_override_npv(
            snapshot, db, launch_delay_months=ovalue
        )

    elif otype == "time_to_peak_change":
        # Use deterministic engine with modified time_to_peak
        npv_after = simulate_override_npv(
            snapshot, db, time_to_peak_change_years=ovalue
        )

    elif otype == "accelerate":
        # Use deterministic engine with duration shift
        phase_name = override.phase_name or "Phase 3"
        npv_after = simulate_override_npv(
            snapshot, db,
            duration_shift={phase_name: -abs(ovalue)},
        )

    elif otype == "budget_realloc":
        # Use deterministic engine with R&D cost multiplier
        npv_after = simulate_override_npv(
            snapshot, db, rd_cost_multiplier=ovalue
        )

    elif otype in ("project_add", "bd_add"):
        # These are structural — NPV contribution handled separately
        npv_after = npv_before  # No direct change to existing project
    
    return {
        "npv_before": npv_before,
        "npv_after": npv_after,
        "is_active": is_active,
    }


# ---------------------------------------------------------------------------
# HYPOTHETICAL PROJECT NPV
# ---------------------------------------------------------------------------

def _calculate_added_project_npv(
    ap: PortfolioAddedProject,
    valuation_year: int = 2025,
    db: Session = None,
) -> float:
    """
    Calculate NPV for a hypothetical added project by creating a temporary
    snapshot and running the deterministic engine for consistent valuation.
    """
    if db is None:
        return 0.0

    from ..models import PhaseInput, RDCost, CommercialRow

    # Parse phases
    try:
        phases = json.loads(ap.phases_json)
    except (json.JSONDecodeError, TypeError):
        phases = []

    # Parse R&D costs
    try:
        rd_costs = json.loads(ap.rd_costs_json)
    except (json.JSONDecodeError, TypeError):
        rd_costs = {}

    launch_year = int(ap.launch_date)
    loe_year = int(ap.loe_year)

    # Create temp asset
    temp_asset = Asset(
        compound_name=f"__temp_added_{ap.id}__",
        therapeutic_area=ap.therapeutic_area or "Unknown",
        current_phase=phases[0]["phase_name"] if phases else "Phase 1",
        innovation_class="Standard",
    )
    db.add(temp_asset)
    db.flush()

    # Create temp snapshot
    temp_snapshot = Snapshot(
        asset_id=temp_asset.id,
        snapshot_name=f"__temp_added_{uuid.uuid4().hex[:8]}__",
        valuation_year=valuation_year,
        horizon_years=max(20, loe_year - valuation_year + 5),
        wacc_rd=ap.wacc_rd,
        approval_date=float(launch_year),
    )
    db.add(temp_snapshot)
    db.flush()

    # Add phase inputs
    for phase in phases:
        db.add(PhaseInput(
            snapshot_id=temp_snapshot.id,
            phase_name=phase.get("phase_name", "Phase 1"),
            start_date=phase.get("start_date", float(valuation_year)),
            success_rate=phase.get("success_rate", 0.5),
        ))

    # Add R&D costs
    for year_str, cost in rd_costs.items():
        year = int(year_str)
        db.add(RDCost(
            snapshot_id=temp_snapshot.id,
            year=year,
            phase_name=phases[0]["phase_name"] if phases else "Phase 1",
            rd_cost=-abs(cost),
        ))

    # Add commercial row
    db.add(CommercialRow(
        snapshot_id=temp_snapshot.id,
        region="Global",
        scenario="Base",
        scenario_probability=1.0,
        segment="Primary",
        peak_sales=ap.peak_sales,
        launch_date=float(launch_year),
        time_to_peak=ap.time_to_peak_years,
        plateau_years=ap.plateau_years,
        loe_year=float(loe_year),
        loe_cliff_rate=ap.loe_cliff_rate,
        erosion_floor_pct=ap.erosion_floor_pct,
        years_to_erosion_floor=ap.years_to_erosion_floor,
        revenue_curve_type="logistic",
        cogs_rate=ap.cogs_rate,
        distribution_rate=0.0,
        operating_cost_rate=ap.operating_cost_rate,
        tax_rate=ap.tax_rate,
        wacc_region=ap.wacc_commercial,
        include_flag=1,
    ))

    db.flush()

    try:
        result = calculate_deterministic_npv(temp_snapshot.id, db)
        return result["npv_deterministic"]
    finally:
        db.delete(temp_asset)
        db.flush()


# ---------------------------------------------------------------------------
# BD PLACEHOLDER NPV
# ---------------------------------------------------------------------------

def _calculate_bd_placeholder_npv(
    bd: PortfolioBDPlaceholder,
    valuation_year: int = 2025,
    db: Session = None,
) -> float:
    """
    Calculate NPV for a BD placeholder asset by creating a temporary
    snapshot and running the deterministic engine for consistent valuation.
    """
    if db is None:
        return 0.0

    from ..models import PhaseInput, RDCost, CommercialRow

    launch_year = int(bd.launch_date)
    loe_year = int(bd.loe_year)

    # Create temp asset
    temp_asset = Asset(
        compound_name=f"__temp_bd_{bd.id}__",
        therapeutic_area=bd.therapeutic_area or "BD",
        current_phase="Registration",
        innovation_class="Standard",
    )
    db.add(temp_asset)
    db.flush()

    # Create temp snapshot
    temp_snapshot = Snapshot(
        asset_id=temp_asset.id,
        snapshot_name=f"__temp_bd_{uuid.uuid4().hex[:8]}__",
        valuation_year=valuation_year,
        horizon_years=max(20, loe_year - valuation_year + 5),
        wacc_rd=bd.wacc_rd,
        approval_date=float(launch_year),
    )
    db.add(temp_snapshot)
    db.flush()

    # Add phase input with PTRS as success rate
    db.add(PhaseInput(
        snapshot_id=temp_snapshot.id,
        phase_name="Registration",
        start_date=float(valuation_year),
        success_rate=bd.ptrs_assumed,
    ))

    # Add upfront payment as R&D cost
    if bd.upfront_payment > 0:
        db.add(RDCost(
            snapshot_id=temp_snapshot.id,
            year=valuation_year,
            phase_name="Registration",
            rd_cost=-bd.upfront_payment,
        ))

    # Add milestone payments as R&D costs
    try:
        milestones = json.loads(bd.milestone_payments_json) if bd.milestone_payments_json else {}
    except (json.JSONDecodeError, TypeError):
        milestones = {}
    for year_str, payment in milestones.items():
        db.add(RDCost(
            snapshot_id=temp_snapshot.id,
            year=int(year_str),
            phase_name="Registration",
            rd_cost=-abs(payment),
        ))

    # Add remaining R&D costs (with cost share)
    try:
        rd_costs = json.loads(bd.rd_cost_remaining_json) if bd.rd_cost_remaining_json else {}
    except (json.JSONDecodeError, TypeError):
        rd_costs = {}
    for year_str, cost in rd_costs.items():
        db.add(RDCost(
            snapshot_id=temp_snapshot.id,
            year=int(year_str),
            phase_name="Registration",
            rd_cost=-abs(cost) * bd.cost_share_pct,
        ))

    # Effective peak sales after revenue share and royalty
    effective_peak = bd.peak_sales * bd.revenue_share_pct * (1.0 - bd.royalty_rate)

    # Add commercial row
    db.add(CommercialRow(
        snapshot_id=temp_snapshot.id,
        region="Global",
        scenario="Base",
        scenario_probability=1.0,
        segment="Primary",
        peak_sales=effective_peak,
        launch_date=float(launch_year),
        time_to_peak=bd.time_to_peak_years,
        plateau_years=float(max(1, loe_year - launch_year - int(bd.time_to_peak_years) - 2)),
        loe_year=float(loe_year),
        loe_cliff_rate=bd.loe_cliff_rate,
        erosion_floor_pct=bd.erosion_floor_pct,
        years_to_erosion_floor=bd.years_to_erosion_floor,
        revenue_curve_type="logistic",
        cogs_rate=bd.cogs_rate,
        distribution_rate=0.0,
        operating_cost_rate=bd.operating_cost_rate,
        tax_rate=bd.tax_rate,
        wacc_region=bd.wacc_commercial,
        include_flag=1,
    ))

    db.flush()

    try:
        result = calculate_deterministic_npv(temp_snapshot.id, db)
        bd.total_deal_cost = bd.upfront_payment + sum(abs(v) for v in milestones.values())
        return result["npv_deterministic"]
    finally:
        db.delete(temp_asset)
        db.flush()


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _get_cashflow_aggregates(
    snapshot_id: int, db: Session, is_active: bool
) -> tuple[dict, dict]:
    """
    Get yearly R&D cost and sales aggregates from stored cashflows.
    Returns (rd_by_year, sales_by_year) dicts.
    """
    if not is_active:
        return {}, {}
    
    cashflows = (
        db.query(Cashflow)
        .filter(
            Cashflow.snapshot_id == snapshot_id,
            Cashflow.cashflow_type == "deterministic",
        )
        .all()
    )
    
    rd_by_year = {}
    sales_by_year = {}
    
    for cf in cashflows:
        year_str = str(cf.year)
        if cf.scope == "R&D":
            rd_by_year[year_str] = rd_by_year.get(year_str, 0) + cf.costs
        else:
            sales_by_year[year_str] = sales_by_year.get(year_str, 0) + cf.revenue
    
    return rd_by_year, sales_by_year


def _merge_yearly(target: dict, source: dict):
    """Merge source year dict into target, summing values."""
    for year, value in source.items():
        target[year] = target.get(year, 0) + value


