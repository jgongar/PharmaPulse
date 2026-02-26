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
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    Portfolio, PortfolioProject, PortfolioScenarioOverride,
    PortfolioResult, PortfolioAddedProject, PortfolioBDPlaceholder,
    Asset, Snapshot, Cashflow,
)
from .. import crud


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
    
    # ---- Process added (hypothetical) projects ----
    added_results = []
    for ap in portfolio.added_projects:
        ap_npv = _calculate_added_project_npv(ap)
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
        bd_npv = _calculate_bd_placeholder_npv(bd)
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
    
    # Clear current overrides
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
    overrides_data = json.loads(run.overrides_snapshot_json)
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
        # ovalue is percentage change, e.g., +10 means multiply by 1.10
        # Approximate NPV impact: revenue portion of NPV scales linearly
        multiplier = 1.0 + (ovalue / 100.0)
        # Rough approximation: assume ~70% of NPV is from commercial revenue
        commercial_portion = npv_before * 0.7
        rd_portion = npv_before * 0.3
        npv_after = commercial_portion * multiplier + rd_portion
    
    elif otype == "sr_override":
        # ovalue is new absolute success rate for a specific phase
        # Impact: changes cumulative probability of success
        phase_name = override.phase_name
        if phase_name and snapshot.phase_inputs:
            # Find original SR for this phase
            original_sr = None
            for pi in snapshot.phase_inputs:
                if pi.phase_name == phase_name:
                    original_sr = pi.success_rate
                    break
            if original_sr and original_sr > 0:
                # Ratio of new/old SR affects the risk-adjusted portion
                sr_ratio = ovalue / original_sr
                npv_after = npv_before * sr_ratio
    
    elif otype == "phase_delay":
        # ovalue is months of delay
        # Impact: time-value-of-money penalty
        months_delay = ovalue
        years_delay = months_delay / 12.0
        wacc = snapshot.wacc_rd or 0.08
        # Discount penalty for delay
        discount_penalty = 1.0 / ((1 + wacc) ** years_delay)
        npv_after = npv_before * discount_penalty
    
    elif otype == "launch_delay":
        # ovalue is months of launch delay
        months_delay = ovalue
        years_delay = months_delay / 12.0
        # Average commercial WACC
        avg_wacc = 0.085
        if snapshot.commercial_rows:
            avg_wacc = sum(
                cr.wacc_region for cr in snapshot.commercial_rows
            ) / len(snapshot.commercial_rows)
        discount_penalty = 1.0 / ((1 + avg_wacc) ** years_delay)
        npv_after = npv_before * discount_penalty
    
    elif otype == "time_to_peak_change":
        # ovalue is change in years to peak (positive = slower ramp)
        # Approximate impact: ~5% NPV per year of slower ramp
        npv_after = npv_before * (1.0 - 0.05 * ovalue)
    
    elif otype == "accelerate":
        # ovalue = months of acceleration (negative means faster)
        # Budget impact via acceleration_budget_multiplier
        months_accel = abs(ovalue)
        years_accel = months_accel / 12.0
        wacc = snapshot.wacc_rd or 0.08
        # Time-value benefit from earlier launch
        time_benefit = (1 + wacc) ** years_accel
        # Budget cost increase
        budget_mult = override.acceleration_budget_multiplier or 1.0
        # Net: benefit from earlier cash flows minus extra R&D cost
        rd_fraction = 0.3  # Approximate R&D fraction of total NPV
        commercial_benefit = (npv_before * (1 - rd_fraction)) * time_benefit
        rd_cost_increase = abs(npv_before * rd_fraction) * budget_mult
        npv_after = commercial_benefit - rd_cost_increase
    
    elif otype == "budget_realloc":
        # ovalue is multiplier for R&D cost of a specific phase
        # Impact: changes R&D portion of NPV
        rd_fraction = 0.3
        rd_portion = abs(npv_before * rd_fraction)
        commercial_portion = npv_before - (-rd_portion if npv_before > 0 else rd_portion)
        new_rd_cost = rd_portion * ovalue
        npv_after = commercial_portion - new_rd_cost
    
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

def _calculate_added_project_npv(ap: PortfolioAddedProject) -> float:
    """
    Calculate NPV for a hypothetical added project using simplified model.
    Uses peak_sales and standard revenue curve assumptions.
    """
    valuation_year = 2025
    horizon = 20
    
    # Parse phases
    try:
        phases = json.loads(ap.phases_json)
    except (json.JSONDecodeError, TypeError):
        phases = []
    
    # Calculate cumulative success probability
    cum_pos = 1.0
    for phase in phases:
        cum_pos *= phase.get("success_rate", 0.5)
    
    # Parse R&D costs
    try:
        rd_costs = json.loads(ap.rd_costs_json)
    except (json.JSONDecodeError, TypeError):
        rd_costs = {}
    
    # Calculate R&D PV
    rd_pv = 0.0
    for year_str, cost in rd_costs.items():
        year = int(year_str)
        t = year - valuation_year
        if t >= 0:
            discount = (1 + ap.wacc_rd) ** t
            rd_pv -= abs(cost) / discount
    
    # Calculate commercial PV
    launch_year = int(ap.launch_date)
    loe_year = int(ap.loe_year)
    time_to_peak = ap.time_to_peak_years
    peak_sales = ap.peak_sales
    
    commercial_pv = 0.0
    for year in range(launch_year, min(loe_year + 5, valuation_year + horizon)):
        t_since_launch = year - launch_year
        t_from_valuation = year - valuation_year
        
        if t_from_valuation < 0:
            continue
        
        # Revenue curve (logistic ramp)
        if t_since_launch < 0:
            revenue = 0
        elif year > loe_year:
            # Post-LOE erosion
            years_post_loe = year - loe_year
            erosion = max(
                ap.erosion_floor_pct,
                1.0 - ap.loe_cliff_rate * (years_post_loe / ap.years_to_erosion_floor)
            )
            revenue = peak_sales * erosion
        else:
            # Ramp-up
            ramp = _logistic_ramp(t_since_launch, time_to_peak)
            # Plateau
            if t_since_launch >= time_to_peak + ap.plateau_years:
                ramp = max(ramp, 1.0)
            revenue = peak_sales * ramp
        
        # Costs
        cogs = revenue * ap.cogs_rate
        opex = revenue * ap.operating_cost_rate
        net_revenue = revenue - cogs - opex
        tax = net_revenue * ap.tax_rate if net_revenue > 0 else 0
        fcf = net_revenue - tax
        
        # Risk adjust
        fcf_ra = fcf * cum_pos
        
        # Discount
        discount = (1 + ap.wacc_commercial) ** t_from_valuation
        commercial_pv += fcf_ra / discount
    
    total_npv = rd_pv + commercial_pv
    return round(total_npv, 2)


# ---------------------------------------------------------------------------
# BD PLACEHOLDER NPV
# ---------------------------------------------------------------------------

def _calculate_bd_placeholder_npv(bd: PortfolioBDPlaceholder) -> float:
    """
    Calculate NPV for a BD placeholder asset.
    Accounts for deal costs (upfront, milestones, royalties),
    revenue/cost sharing, and PTRS.
    """
    valuation_year = 2025
    horizon = 20
    
    ptrs = bd.ptrs_assumed
    launch_year = int(bd.launch_date)
    loe_year = int(bd.loe_year)
    peak_sales = bd.peak_sales
    time_to_peak = bd.time_to_peak_years
    
    # Upfront payment (immediate cost)
    deal_costs_pv = -bd.upfront_payment
    
    # Milestone payments
    try:
        milestones = json.loads(bd.milestone_payments_json) if bd.milestone_payments_json else {}
    except (json.JSONDecodeError, TypeError):
        milestones = {}
    
    for year_str, payment in milestones.items():
        year = int(year_str)
        t = year - valuation_year
        if t >= 0:
            discount = (1 + bd.wacc_rd) ** t
            deal_costs_pv -= abs(payment) / discount
    
    # R&D costs remaining
    rd_pv = 0.0
    try:
        rd_costs = json.loads(bd.rd_cost_remaining_json) if bd.rd_cost_remaining_json else {}
    except (json.JSONDecodeError, TypeError):
        rd_costs = {}
    
    for year_str, cost in rd_costs.items():
        year = int(year_str)
        t = year - valuation_year
        if t >= 0:
            discount = (1 + bd.wacc_rd) ** t
            rd_pv -= abs(cost) * bd.cost_share_pct / discount
    
    # Commercial revenue
    commercial_pv = 0.0
    for year in range(launch_year, min(loe_year + 5, valuation_year + horizon)):
        t_since_launch = year - launch_year
        t_from_valuation = year - valuation_year
        
        if t_from_valuation < 0:
            continue
        
        # Revenue curve
        if t_since_launch < 0:
            revenue = 0
        elif year > loe_year:
            years_post_loe = year - loe_year
            erosion = max(
                bd.erosion_floor_pct,
                1.0 - bd.loe_cliff_rate * (years_post_loe / bd.years_to_erosion_floor)
            )
            revenue = peak_sales * erosion
        else:
            ramp = _logistic_ramp(t_since_launch, time_to_peak)
            revenue = peak_sales * ramp
        
        # Apply revenue share
        revenue *= bd.revenue_share_pct
        
        # Deduct royalty
        royalty = revenue * bd.royalty_rate
        net_after_royalty = revenue - royalty
        
        # Costs
        cogs = net_after_royalty * bd.cogs_rate
        opex = net_after_royalty * bd.operating_cost_rate
        net_income = net_after_royalty - cogs - opex
        tax = net_income * bd.tax_rate if net_income > 0 else 0
        fcf = net_income - tax
        
        # Risk adjust with PTRS
        fcf_ra = fcf * ptrs
        
        # Discount
        discount = (1 + bd.wacc_commercial) ** t_from_valuation
        commercial_pv += fcf_ra / discount
    
    total_npv = deal_costs_pv + rd_pv + commercial_pv
    
    # Store total deal cost for reporting
    bd.total_deal_cost = abs(deal_costs_pv)
    
    return round(total_npv, 2)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _logistic_ramp(t: float, time_to_peak: float, k: float = 5.5) -> float:
    """
    Logistic revenue ramp-up function.
    Returns a value between 0 and 1 representing fraction of peak sales.
    """
    if time_to_peak <= 0:
        return 1.0
    midpoint = time_to_peak * 0.5
    exponent = -k * (t - midpoint) / time_to_peak
    try:
        return 1.0 / (1.0 + math.exp(exponent))
    except OverflowError:
        return 0.0 if exponent > 0 else 1.0


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


