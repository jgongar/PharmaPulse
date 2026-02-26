"""
PharmaPulse — Family A: Kill / Continue / Accelerate Engine

Provides analysis tools for project go/no-go and acceleration decisions:
  - Kill Analysis:          NPV lost, budget freed, portfolio impact
  - Acceleration Analysis:  Budget-to-timeline trade-off with concave curve
  - Kill & Reinvest:        Combined kill + acceleration with budget flow

Acceleration Curve Model:
  timeline_reduction_fraction = alpha * ln(budget_multiplier)
  where alpha = 0.5, budget_multiplier in [1.0, 2.0]
  Cap: reduction <= 50% of original duration
"""

import math
from typing import Optional
from functools import reduce
import operator

from sqlalchemy.orm import Session

from ..models import (
    Portfolio, PortfolioProject, PortfolioScenarioOverride,
    PortfolioResult, Asset, Snapshot, Cashflow,
)
from .. import crud


# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

ACCELERATION_ALPHA = 0.5        # Calibration constant for acceleration curve
MAX_BUDGET_MULTIPLIER = 2.0     # Maximum budget multiplier
MAX_TIMELINE_REDUCTION = 0.50   # Cap: no phase can be reduced by more than 50%


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _compute_pts(snapshot: Snapshot) -> float:
    """Compute overall PTS as product of all phase success rates."""
    if not snapshot.phase_inputs:
        return 0.0
    return reduce(operator.mul, (pi.success_rate for pi in snapshot.phase_inputs), 1.0)


def _compute_phase_duration_months(snapshot: Snapshot, phase_name: str) -> float:
    """
    Compute duration of a phase in months from sequential start dates.
    Duration = next_phase_start - this_phase_start (in years) * 12
    For the last phase, use approval_date - last_phase_start.
    """
    phases = sorted(
        [(pi.phase_name, pi.start_date) for pi in snapshot.phase_inputs],
        key=lambda x: x[1],
    )
    for i, (pname, start) in enumerate(phases):
        if pname == phase_name:
            if i + 1 < len(phases):
                end = phases[i + 1][1]
            else:
                end = snapshot.approval_date
            return max((end - start) * 12, 6)  # At least 6 months
    return 24.0  # Default fallback


def _total_rd_cost(snapshot: Snapshot) -> float:
    """Sum all R&D costs for a snapshot."""
    return sum(abs(rc.rd_cost) for rc in snapshot.rd_costs)


def _phase_rd_cost(snapshot: Snapshot, phase_name: str) -> float:
    """Sum R&D costs for a specific phase."""
    return sum(abs(rc.rd_cost) for rc in snapshot.rd_costs if rc.phase_name == phase_name)


# ---------------------------------------------------------------------------
# ACCELERATION CURVE
# ---------------------------------------------------------------------------

def acceleration_curve(budget_multiplier: float) -> float:
    """
    Compute timeline reduction fraction from budget multiplier.
    Uses concave logarithmic model: reduction = alpha * ln(budget_multiplier).
    """
    if budget_multiplier <= 1.0:
        return 0.0
    bm = min(budget_multiplier, MAX_BUDGET_MULTIPLIER)
    reduction = ACCELERATION_ALPHA * math.log(bm)
    return min(reduction, MAX_TIMELINE_REDUCTION)


def generate_acceleration_curve_data(
    original_duration_months: float,
    original_cost: float,
) -> list[dict]:
    """Generate full acceleration curve data for visualization."""
    points = []
    for bm_pct in range(100, 201, 5):
        bm = bm_pct / 100.0
        reduction_frac = acceleration_curve(bm)
        months_saved = reduction_frac * original_duration_months
        additional_cost = (bm - 1.0) * original_cost
        new_duration = original_duration_months - months_saved

        points.append({
            "budget_multiplier": round(bm, 2),
            "timeline_reduction_pct": round(reduction_frac * 100, 1),
            "months_saved": round(months_saved, 1),
            "new_duration_months": round(new_duration, 1),
            "additional_cost_eur_mm": round(additional_cost, 1),
        })
    return points


# ---------------------------------------------------------------------------
# KILL ANALYSIS
# ---------------------------------------------------------------------------

def analyze_kill_impact(portfolio_id: int, asset_id: int, db: Session) -> dict:
    """
    Analyze the financial impact of killing a project in a portfolio.
    """
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    project = None
    for proj in portfolio.projects:
        if proj.asset_id == asset_id:
            project = proj
            break

    if not project:
        raise ValueError(f"Asset {asset_id} not found in portfolio {portfolio_id}")

    asset = project.asset
    snapshot = project.snapshot

    if not snapshot:
        raise ValueError(f"No snapshot for asset {asset_id}")

    npv_lost = snapshot.npv_deterministic or 0.0

    # Get R&D costs from cashflows
    rd_cashflows = (
        db.query(Cashflow)
        .filter(
            Cashflow.snapshot_id == snapshot.id,
            Cashflow.cashflow_type == "deterministic",
            Cashflow.scope == "R&D",
        )
        .all()
    )

    budget_freed_by_year = {}
    budget_freed_total = 0.0
    for cf in rd_cashflows:
        cost_positive = abs(cf.costs) if cf.costs else 0.0
        if cost_positive > 0:
            budget_freed_by_year[str(cf.year)] = round(cost_positive, 2)
            budget_freed_total += cost_positive

    # If no R&D cashflows, fall back to rd_costs table
    if budget_freed_total == 0:
        for rc in snapshot.rd_costs:
            cost_positive = abs(rc.rd_cost)
            if cost_positive > 0:
                yr = str(rc.year)
                budget_freed_by_year[yr] = round(
                    budget_freed_by_year.get(yr, 0) + cost_positive, 2
                )
                budget_freed_total += cost_positive

    portfolio_npv_before = portfolio.total_npv or 0.0
    portfolio_npv_after = portfolio_npv_before - npv_lost

    return {
        "asset_id": asset_id,
        "compound_name": asset.compound_name,
        "therapeutic_area": asset.therapeutic_area,
        "current_phase": asset.current_phase,
        "npv_lost": round(npv_lost, 2),
        "budget_freed_total": round(budget_freed_total, 2),
        "budget_freed_by_year": budget_freed_by_year,
        "portfolio_npv_before": round(portfolio_npv_before, 2),
        "portfolio_npv_after": round(portfolio_npv_after, 2),
        "portfolio_delta": round(-npv_lost, 2),
        "portfolio_delta_pct": round(
            (-npv_lost / abs(portfolio_npv_before) * 100)
            if portfolio_npv_before != 0 else 0, 1
        ),
        "recommendation": _kill_recommendation(npv_lost, budget_freed_total),
    }


def _kill_recommendation(npv_lost: float, budget_freed: float) -> str:
    if npv_lost <= 0:
        return (
            f"Project has negative or zero NPV ({npv_lost:,.1f} EUR mm). "
            f"Killing frees {budget_freed:,.1f} EUR mm in R&D budget. "
            f"Recommendation: KILL - project destroys value."
        )
    ratio = budget_freed / abs(npv_lost) if npv_lost != 0 else 0
    if ratio > 0.5:
        return (
            f"Killing loses {npv_lost:,.1f} EUR mm NPV but frees {budget_freed:,.1f} EUR mm. "
            f"Budget-to-NPV ratio: {ratio:.2f}. "
            f"Consider killing if freed budget can generate higher NPV elsewhere."
        )
    return (
        f"Killing loses {npv_lost:,.1f} EUR mm NPV and frees {budget_freed:,.1f} EUR mm. "
        f"Budget-to-NPV ratio: {ratio:.2f}. "
        f"Project appears valuable relative to remaining investment. Recommend CONTINUE."
    )


# ---------------------------------------------------------------------------
# ACCELERATION ANALYSIS
# ---------------------------------------------------------------------------

def analyze_acceleration(
    portfolio_id: int,
    asset_id: int,
    budget_multiplier: float,
    db: Session,
    phase_name: Optional[str] = None,
) -> dict:
    """
    Analyze the impact of accelerating a project's timeline.
    """
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    project = None
    for proj in portfolio.projects:
        if proj.asset_id == asset_id:
            project = proj
            break

    if not project:
        raise ValueError(f"Asset {asset_id} not found in portfolio {portfolio_id}")

    asset = project.asset
    snapshot = project.snapshot

    if not snapshot:
        raise ValueError(f"No snapshot for asset {asset_id}")

    # Determine which phase to accelerate
    if not phase_name:
        phase_name = asset.current_phase

    # Compute phase duration from start dates
    original_duration = _compute_phase_duration_months(snapshot, phase_name)

    # Get phase R&D cost
    phase_cost = _phase_rd_cost(snapshot, phase_name)
    if phase_cost == 0:
        total_rd = _total_rd_cost(snapshot)
        phase_count = len(snapshot.phase_inputs) or 1
        phase_cost = total_rd / phase_count

    # Apply acceleration curve
    bm = min(max(budget_multiplier, 1.0), MAX_BUDGET_MULTIPLIER)
    reduction_frac = acceleration_curve(bm)
    months_saved = reduction_frac * original_duration
    additional_cost = (bm - 1.0) * phase_cost
    new_duration = original_duration - months_saved

    # Estimate NPV gain from earlier commercialization
    original_npv = snapshot.npv_deterministic or 0.0
    years_saved = months_saved / 12.0
    wacc = snapshot.wacc_rd or 0.08
    commercial_fraction = 0.7
    npv_gain = original_npv * commercial_fraction * ((1 + wacc) ** years_saved - 1)
    net_npv_impact = npv_gain - additional_cost

    curve_data = generate_acceleration_curve_data(original_duration, phase_cost)

    return {
        "asset_id": asset_id,
        "compound_name": asset.compound_name,
        "phase_name": phase_name,
        "original_duration_months": round(original_duration, 1),
        "new_duration_months": round(new_duration, 1),
        "months_saved": round(months_saved, 1),
        "budget_multiplier": round(bm, 2),
        "original_phase_cost": round(phase_cost, 2),
        "additional_cost": round(additional_cost, 2),
        "total_phase_cost": round(phase_cost + additional_cost, 2),
        "original_npv": round(original_npv, 2),
        "estimated_npv_gain": round(npv_gain, 2),
        "net_npv_impact": round(net_npv_impact, 2),
        "acceleration_curve": curve_data,
        "recommendation": _acceleration_recommendation(
            months_saved, additional_cost, npv_gain, net_npv_impact
        ),
    }


def _acceleration_recommendation(
    months_saved: float, cost: float, npv_gain: float, net_impact: float
) -> str:
    if net_impact > 0:
        return (
            f"Accelerating by {months_saved:.0f} months costs {cost:,.1f} EUR mm "
            f"but gains ~{npv_gain:,.1f} EUR mm in NPV. "
            f"Net positive impact: +{net_impact:,.1f} EUR mm. "
            f"Recommendation: ACCELERATE."
        )
    return (
        f"Accelerating by {months_saved:.0f} months costs {cost:,.1f} EUR mm "
        f"with estimated NPV gain of {npv_gain:,.1f} EUR mm. "
        f"Net impact: {net_impact:,.1f} EUR mm. "
        f"Acceleration may not be cost-effective at this budget level."
    )


# ---------------------------------------------------------------------------
# KILL AND REINVEST
# ---------------------------------------------------------------------------

def analyze_kill_and_reinvest(
    portfolio_id: int,
    kill_asset_id: int,
    accelerate_asset_id: int,
    db: Session,
    accelerate_phase_name: Optional[str] = None,
) -> dict:
    """
    Combined analysis: kill one project and reinvest freed budget to accelerate another.
    """
    # Step 1: Kill analysis
    kill_result = analyze_kill_impact(portfolio_id, kill_asset_id, db)
    budget_freed = kill_result["budget_freed_total"]

    # Step 2: Find acceleration target
    portfolio = crud.get_portfolio(db, portfolio_id)
    accel_project = None
    for proj in portfolio.projects:
        if proj.asset_id == accelerate_asset_id:
            accel_project = proj
            break

    if not accel_project:
        raise ValueError(
            f"Asset {accelerate_asset_id} not found in portfolio {portfolio_id}"
        )

    snapshot = accel_project.snapshot
    if not snapshot:
        raise ValueError(f"No snapshot for asset {accelerate_asset_id}")

    target_phase = accelerate_phase_name or accel_project.asset.current_phase
    phase_cost = _phase_rd_cost(snapshot, target_phase)

    if phase_cost == 0:
        total_rd = _total_rd_cost(snapshot)
        phase_count = len(snapshot.phase_inputs) or 1
        phase_cost = total_rd / phase_count

    # Step 3: Compute budget multiplier
    if phase_cost > 0:
        computed_multiplier = 1.0 + (budget_freed / phase_cost)
    else:
        computed_multiplier = MAX_BUDGET_MULTIPLIER

    actual_multiplier = min(computed_multiplier, MAX_BUDGET_MULTIPLIER)
    budget_used = (actual_multiplier - 1.0) * phase_cost
    budget_surplus = max(0, budget_freed - budget_used)

    # Step 4: Acceleration analysis
    accel_result = analyze_acceleration(
        portfolio_id, accelerate_asset_id, actual_multiplier, db, target_phase
    )

    # Step 5: Net impact
    npv_lost = kill_result["npv_lost"]
    npv_gained = accel_result["estimated_npv_gain"]
    net_npv_delta = npv_gained - npv_lost

    return {
        "kill_analysis": kill_result,
        "acceleration_analysis": accel_result,
        "budget_flow": {
            "freed_from_kill": round(budget_freed, 2),
            "used_for_acceleration": round(budget_used, 2),
            "budget_surplus": round(budget_surplus, 2),
            "computed_multiplier": round(computed_multiplier, 2),
            "actual_multiplier": round(actual_multiplier, 2),
        },
        "net_impact": {
            "npv_lost_from_kill": round(npv_lost, 2),
            "npv_gained_from_acceleration": round(npv_gained, 2),
            "net_npv_delta": round(net_npv_delta, 2),
            "net_npv_delta_pct": round(
                (net_npv_delta / abs(kill_result["portfolio_npv_before"]) * 100)
                if kill_result["portfolio_npv_before"] != 0 else 0, 1
            ),
        },
        "recommendation": _reinvest_recommendation(
            kill_result["compound_name"],
            accel_result["compound_name"],
            npv_lost, npv_gained, net_npv_delta, budget_surplus,
        ),
    }


def _reinvest_recommendation(
    kill_name: str, accel_name: str,
    npv_lost: float, npv_gained: float, net_delta: float, surplus: float,
) -> str:
    if net_delta > 0:
        text = (
            f"Killing {kill_name} and reinvesting in {accel_name} has a "
            f"net positive impact of +{net_delta:,.1f} EUR mm. "
        )
        if surplus > 0:
            text += f"Additionally, {surplus:,.1f} EUR mm budget surplus remains. "
        text += "Recommendation: PROCEED with kill and reinvest."
        return text
    return (
        f"Killing {kill_name} (-{npv_lost:,.1f}) and reinvesting in {accel_name} "
        f"(+{npv_gained:,.1f}) has a net impact of {net_delta:,.1f} EUR mm. "
        f"The trade-off may not be favorable. Consider alternative reinvestment targets."
    )
