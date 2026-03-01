"""
PharmaPulse — Deterministic rNPV Engine

Main entry point for risk-adjusted Net Present Value calculation.

Process (from Spec Section 6):
    1. Load all inputs from database for this snapshot
    2. Build fractional timeline (phase durations, cumulative POS)
    3. If what-if levers exist on snapshot:
       a. Apply duration levers first (shifts timeline)
       b. Apply SR overrides
       c. Apply revenue lever to commercial cashflows
       d. Apply R&D cost lever
    4. Calculate R&D cashflows by year (risk-adjusted, discounted)
    5. Calculate commercial cashflows by region × scenario × segment
    6. Compute deterministic NPV = R&D NPV + Σ(region probability-weighted NPV)
    7. Store all cashflows in the cashflows table
    8. Update snapshot and asset records with results
    9. Return results dict
"""

import math
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    Asset, Snapshot, PhaseInput, RDCost, CommercialRow,
    WhatIfPhaseLever, Cashflow,
)
from .risk_adjustment import (
    PHASE_ORDER, compute_cumulative_pos,
    get_phase_cost_multiplier, get_commercial_multiplier,
)
from .revenue_curves import compute_annual_revenue, compute_peak_revenue_for_row
from .discounting import discount_cashflow


def calculate_deterministic_npv(
    snapshot_id: int,
    db: Session,
    is_whatif: bool = False,
) -> dict:
    """
    Main entry point for deterministic rNPV calculation.

    Args:
        snapshot_id: ID of the snapshot to calculate.
        db: SQLAlchemy session.
        is_whatif: If True, applies what-if levers and stores results
                   as "deterministic_whatif" cashflow type.

    Returns:
        Dict with:
            - npv_deterministic: float (total NPV in EUR mm)
            - npv_rd: float (R&D NPV component)
            - npv_commercial: float (commercial NPV component)
            - npv_by_region_scenario: dict of {region: {scenario: npv}}
            - peak_sales_total: float (aggregate peak sales EUR mm)
            - cashflows: list of cashflow dicts
            - cumulative_pos: float
    """
    # ------------------------------------------------------------------
    # 1. Load all inputs
    # ------------------------------------------------------------------
    snapshot = db.query(Snapshot).filter(Snapshot.id == snapshot_id).first()
    if not snapshot:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    asset = db.query(Asset).filter(Asset.id == snapshot.asset_id).first()
    if not asset:
        raise ValueError(f"Asset {snapshot.asset_id} not found")

    phase_inputs = (
        db.query(PhaseInput)
        .filter(PhaseInput.snapshot_id == snapshot_id)
        .order_by(PhaseInput.start_date)
        .all()
    )

    rd_costs = (
        db.query(RDCost)
        .filter(RDCost.snapshot_id == snapshot_id)
        .all()
    )

    commercial_rows = (
        db.query(CommercialRow)
        .filter(CommercialRow.snapshot_id == snapshot_id)
        .filter(CommercialRow.include_flag == 1)
        .all()
    )

    whatif_phase_levers = []
    if is_whatif:
        whatif_phase_levers = (
            db.query(WhatIfPhaseLever)
            .filter(WhatIfPhaseLever.snapshot_id == snapshot_id)
            .all()
        )

    # ------------------------------------------------------------------
    # 2. Apply what-if levers (if applicable)
    # ------------------------------------------------------------------
    sr_overrides = {}
    duration_shifts = {}  # {phase_name: months_to_add}
    revenue_lever = 1.0
    rd_cost_lever = 1.0

    if is_whatif:
        # Revenue and R&D cost levers from snapshot
        if snapshot.whatif_revenue_lever is not None:
            revenue_lever = snapshot.whatif_revenue_lever
        if snapshot.whatif_rd_cost_lever is not None:
            rd_cost_lever = snapshot.whatif_rd_cost_lever

        # Phase-level SR and duration levers
        for lever in whatif_phase_levers:
            if lever.lever_sr is not None:
                sr_overrides[lever.phase_name] = lever.lever_sr
            if lever.lever_duration_months != 0:
                duration_shifts[lever.phase_name] = lever.lever_duration_months

    # ------------------------------------------------------------------
    # 3. Build timeline & apply duration shifts
    # ------------------------------------------------------------------
    # Build phase timeline (apply duration shifts if what-if)
    phase_timeline = _build_phase_timeline(
        phase_inputs, snapshot.approval_date, duration_shifts
    )

    # Compute approval date (may have shifted due to duration levers)
    effective_approval_date = phase_timeline.get(
        "effective_approval_date", snapshot.approval_date
    )

    # Cascade duration shifts to R&D cost years
    if duration_shifts:
        total_shift_years = phase_timeline.get("total_shift_years", 0)
        phase_shifts = phase_timeline.get("phases", {})
        for cost in rd_costs:
            # Shift costs for phases that were delayed
            if cost.phase_name in phase_shifts:
                phase_info = phase_shifts[cost.phase_name]
                phase_shift = phase_info["shifted_start"] - phase_info["original_start"]
                if phase_shift != 0:
                    cost.year = cost.year + round(phase_shift)

    # ------------------------------------------------------------------
    # 4. Compute risk adjustment multipliers
    # ------------------------------------------------------------------
    pos_result = compute_cumulative_pos(
        phase_inputs, asset.current_phase, sr_overrides
    )
    commercial_multiplier = get_commercial_multiplier(pos_result)

    # ------------------------------------------------------------------
    # 5. Calculate R&D cashflows
    # ------------------------------------------------------------------
    valuation_year = snapshot.valuation_year
    horizon_end = valuation_year + snapshot.horizon_years
    cashflow_type = "deterministic_whatif" if is_whatif else "deterministic"

    rd_cashflows = []
    npv_rd = 0.0
    current_phase_idx = PHASE_ORDER.index(asset.current_phase) if asset.current_phase and asset.current_phase in PHASE_ORDER else 0

    for cost in rd_costs:
        # Skip sunk costs (before valuation year)
        if cost.year < valuation_year:
            continue

        # Skip costs for phases before current_phase (already sunk)
        cost_phase_idx = PHASE_ORDER.index(cost.phase_name) if cost.phase_name in PHASE_ORDER else -1
        if cost_phase_idx < current_phase_idx:
            continue

        # Get the risk multiplier for this phase's costs
        cost_multiplier = get_phase_cost_multiplier(pos_result, cost.phase_name)

        # Apply R&D cost lever (what-if)
        raw_cost = cost.rd_cost * rd_cost_lever

        # Risk-adjust
        risk_adj_cost = raw_cost * cost_multiplier

        # Discount
        pv = discount_cashflow(risk_adj_cost, cost.year, valuation_year, snapshot.wacc_rd)

        npv_rd += pv

        rd_cashflows.append({
            "year": cost.year,
            "scope": "R&D",
            "revenue": 0.0,
            "costs": raw_cost,
            "tax": 0.0,
            "fcf_non_risk_adj": raw_cost,
            "risk_multiplier": cost_multiplier,
            "fcf_risk_adj": risk_adj_cost,
            "fcf_pv": pv,
        })

    # ------------------------------------------------------------------
    # 6. Calculate commercial cashflows by region × scenario
    # ------------------------------------------------------------------
    # Group commercial rows by (region, scenario)
    region_scenario_groups = defaultdict(list)
    for row in commercial_rows:
        key = (row.region, row.scenario)
        region_scenario_groups[key].append(row)

    # Validate scenario probabilities sum to ~1.0 per region
    region_prob_sums = defaultdict(float)
    for (region, scenario), rows in region_scenario_groups.items():
        region_prob_sums[region] += rows[0].scenario_probability
    for region, prob_sum in region_prob_sums.items():
        if abs(prob_sum - 1.0) > 0.01:
            raise ValueError(
                f"Scenario probabilities for region '{region}' sum to {prob_sum:.4f}, "
                f"expected ~1.0"
            )

    commercial_cashflows = []
    npv_by_region_scenario = defaultdict(lambda: defaultdict(float))
    peak_sales_by_region = {}
    total_peak_sales = 0.0
    npv_commercial = 0.0

    for (region, scenario), rows in region_scenario_groups.items():
        scenario_prob = rows[0].scenario_probability  # Same for all rows in group
        wacc_region = rows[0].wacc_region

        # Compute peak revenue for each segment in this region-scenario
        segment_peaks = []
        for row in rows:
            seg_peak = compute_peak_revenue_for_row(row)
            segment_peaks.append((row, seg_peak))

        regional_peak = sum(sp for _, sp in segment_peaks)
        peak_sales_by_region[f"{region}_{scenario}"] = regional_peak
        total_peak_sales += regional_peak * scenario_prob  # Weighted

        # Compute launch_date for this region (may be shifted by duration levers)
        # Duration shifts affect approval_date → commercial launch shifts by same delta
        base_launch = rows[0].launch_date
        if duration_shifts:
            # Compute total timeline shift
            total_shift_years = phase_timeline.get("total_shift_years", 0)
            effective_launch = base_launch + total_shift_years
        else:
            effective_launch = base_launch

        # For each year in horizon, compute revenue and FCF
        region_scenario_npv = 0.0

        for year in range(valuation_year, horizon_end + 1):
            # Compute revenue for this year across all segments
            year_revenue = 0.0
            for row, seg_peak in segment_peaks:
                # Get LOE and curve params from first row (shared across segments)
                seg_revenue = compute_annual_revenue(
                    peak_revenue=seg_peak,
                    launch_date=effective_launch,
                    time_to_peak=row.time_to_peak,
                    plateau_years=row.plateau_years,
                    loe_year=row.loe_year,
                    loe_cliff_rate=row.loe_cliff_rate,
                    erosion_floor_pct=row.erosion_floor_pct,
                    years_to_erosion_floor=row.years_to_erosion_floor,
                    revenue_curve_type=row.revenue_curve_type,
                    logistic_k=row.logistic_k if row.logistic_k is not None else 5.5,
                    logistic_midpoint=row.logistic_midpoint if row.logistic_midpoint is not None else 0.5,
                    year=year,
                )
                year_revenue += seg_revenue

            if year_revenue <= 0:
                continue

            # Apply revenue lever (what-if)
            year_revenue *= revenue_lever

            # Known limitation: cost rates (COGS, distribution, operating) are taken
            # from the first row in this region-scenario group. When multiple segments
            # exist with different cost structures, this is an approximation.
            rep_row = rows[0]
            cogs = year_revenue * rep_row.cogs_rate
            distribution = year_revenue * rep_row.distribution_rate
            operating = year_revenue * rep_row.operating_cost_rate
            total_costs = cogs + distribution + operating
            ebit = year_revenue - total_costs
            tax = max(0, ebit * rep_row.tax_rate)
            fcf = ebit - tax

            # Risk-adjust
            fcf_risk_adj = fcf * commercial_multiplier

            # Discount
            pv = discount_cashflow(fcf_risk_adj, year, valuation_year, wacc_region)

            region_scenario_npv += pv

            commercial_cashflows.append({
                "year": year,
                "scope": region,
                "revenue": year_revenue,
                "costs": -(total_costs),
                "tax": -tax,
                "fcf_non_risk_adj": fcf,
                "risk_multiplier": commercial_multiplier,
                "fcf_risk_adj": fcf_risk_adj,
                "fcf_pv": pv,
                "_scenario": scenario,
                "_scenario_prob": scenario_prob,
            })

        # Weight by scenario probability
        weighted_npv = region_scenario_npv * scenario_prob
        npv_by_region_scenario[region][scenario] = region_scenario_npv
        npv_commercial += weighted_npv

    # ------------------------------------------------------------------
    # 7. Compute total NPV
    # ------------------------------------------------------------------
    npv_total = npv_rd + npv_commercial

    # ------------------------------------------------------------------
    # 8. Store cashflows in database
    # ------------------------------------------------------------------
    _store_cashflows(
        db, snapshot_id, cashflow_type,
        rd_cashflows, commercial_cashflows,
    )

    # ------------------------------------------------------------------
    # 9. Update snapshot and asset records
    # ------------------------------------------------------------------
    if is_whatif:
        snapshot.npv_deterministic_whatif = round(npv_total, 2)
    else:
        snapshot.npv_deterministic = round(npv_total, 2)
        # Also update asset peak_sales
        asset.peak_sales_estimate = round(total_peak_sales, 2)

    db.commit()

    # ------------------------------------------------------------------
    # 10. Build and return results
    # ------------------------------------------------------------------
    # Flatten npv_by_region_scenario for JSON
    npv_by_rs = {}
    for region, scenarios in npv_by_region_scenario.items():
        npv_by_rs[region] = dict(scenarios)

    return {
        "snapshot_id": snapshot_id,
        "cashflow_type": cashflow_type,
        "npv_deterministic": round(npv_total, 2),
        "npv_rd": round(npv_rd, 2),
        "npv_commercial": round(npv_commercial, 2),
        "npv_by_region_scenario": npv_by_rs,
        "peak_sales_total": round(total_peak_sales, 2),
        "cumulative_pos": round(commercial_multiplier, 6),
        "valuation_year": valuation_year,
        "horizon_end": horizon_end,
        "levers_applied": is_whatif,
        "revenue_lever": revenue_lever if is_whatif else None,
        "rd_cost_lever": rd_cost_lever if is_whatif else None,
    }


# ==========================================================================
# HELPER FUNCTIONS
# ==========================================================================

def _build_phase_timeline(
    phase_inputs: list,
    approval_date: float,
    duration_shifts: dict,
) -> dict:
    """
    Builds a phase timeline accounting for duration shifts.
    
    If duration shifts are applied:
    - Modify the duration of the target phase
    - Cascade the shift to all subsequent phases and approval date
    
    Args:
        phase_inputs: List of PhaseInput ORM objects.
        approval_date: Original approval date from snapshot.
        duration_shifts: Dict of {phase_name: months_to_add}.
    
    Returns:
        Dict with effective dates and total shift in years.
    """
    if not duration_shifts:
        return {
            "effective_approval_date": approval_date,
            "total_shift_years": 0,
            "phases": {},
        }

    # Build sorted phase list
    phases = sorted(
        [(pi.phase_name, pi.start_date) for pi in phase_inputs],
        key=lambda x: x[1],
    )

    total_shift_months = 0
    result_phases = {}

    for i, (phase_name, start_date) in enumerate(phases):
        # Apply accumulated shift to this phase's start date
        shifted_start = start_date + (total_shift_months / 12.0)

        # If this phase has a duration shift, add it
        if phase_name in duration_shifts:
            total_shift_months += duration_shifts[phase_name]

        result_phases[phase_name] = {
            "original_start": start_date,
            "shifted_start": shifted_start,
        }

    total_shift_years = total_shift_months / 12.0
    effective_approval = approval_date + total_shift_years

    return {
        "effective_approval_date": effective_approval,
        "total_shift_years": total_shift_years,
        "phases": result_phases,
    }


def _store_cashflows(
    db: Session,
    snapshot_id: int,
    cashflow_type: str,
    rd_cashflows: list,
    commercial_cashflows: list,
):
    """
    Stores calculated cashflows in the database.
    Clears existing cashflows for this snapshot_id + type first.
    """
    # Delete existing cashflows for this type
    db.query(Cashflow).filter(
        Cashflow.snapshot_id == snapshot_id,
        Cashflow.cashflow_type == cashflow_type,
    ).delete()

    # Aggregate commercial cashflows by (year, scope/region)
    # Multiple scenarios for same region-year need to be probability-weighted
    aggregated = defaultdict(lambda: {
        "revenue": 0.0, "costs": 0.0, "tax": 0.0,
        "fcf_non_risk_adj": 0.0, "risk_multiplier": 1.0,
        "fcf_risk_adj": 0.0, "fcf_pv": 0.0,
    })

    for cf in commercial_cashflows:
        key = (cf["year"], cf["scope"])
        prob = cf.get("_scenario_prob", 1.0)
        agg = aggregated[key]
        agg["revenue"] += cf["revenue"] * prob
        agg["costs"] += cf["costs"] * prob
        agg["tax"] += cf["tax"] * prob
        agg["fcf_non_risk_adj"] += cf["fcf_non_risk_adj"] * prob
        agg["risk_multiplier"] = cf["risk_multiplier"]  # Same for all
        agg["fcf_risk_adj"] += cf["fcf_risk_adj"] * prob
        agg["fcf_pv"] += cf["fcf_pv"] * prob

    # Store R&D cashflows
    for cf in rd_cashflows:
        db.add(Cashflow(
            snapshot_id=snapshot_id,
            cashflow_type=cashflow_type,
            scope=cf["scope"],
            year=cf["year"],
            revenue=cf["revenue"],
            costs=cf["costs"],
            tax=cf["tax"],
            fcf_non_risk_adj=cf["fcf_non_risk_adj"],
            risk_multiplier=cf["risk_multiplier"],
            fcf_risk_adj=cf["fcf_risk_adj"],
            fcf_pv=cf["fcf_pv"],
        ))

    # Store aggregated commercial cashflows
    for (year, scope), vals in aggregated.items():
        db.add(Cashflow(
            snapshot_id=snapshot_id,
            cashflow_type=cashflow_type,
            scope=scope,
            year=year,
            revenue=round(vals["revenue"], 4),
            costs=round(vals["costs"], 4),
            tax=round(vals["tax"], 4),
            fcf_non_risk_adj=round(vals["fcf_non_risk_adj"], 4),
            risk_multiplier=round(vals["risk_multiplier"], 6),
            fcf_risk_adj=round(vals["fcf_risk_adj"], 4),
            fcf_pv=round(vals["fcf_pv"], 4),
        ))

    # Store totals row per year
    all_years = set()
    for cf in rd_cashflows:
        all_years.add(cf["year"])
    for (year, _) in aggregated.keys():
        all_years.add(year)

    for year in sorted(all_years):
        total_rev = 0.0
        total_costs = 0.0
        total_tax = 0.0
        total_fcf = 0.0
        total_fcf_ra = 0.0
        total_pv = 0.0

        # R&D for this year
        for cf in rd_cashflows:
            if cf["year"] == year:
                total_costs += cf["costs"]
                total_fcf += cf["fcf_non_risk_adj"]
                total_fcf_ra += cf["fcf_risk_adj"]
                total_pv += cf["fcf_pv"]

        # Commercial for this year
        for (y, _scope), vals in aggregated.items():
            if y == year:
                total_rev += vals["revenue"]
                total_costs += vals["costs"]
                total_tax += vals["tax"]
                total_fcf += vals["fcf_non_risk_adj"]
                total_fcf_ra += vals["fcf_risk_adj"]
                total_pv += vals["fcf_pv"]

        db.add(Cashflow(
            snapshot_id=snapshot_id,
            cashflow_type=cashflow_type,
            scope="Total",
            year=year,
            revenue=round(total_rev, 4),
            costs=round(total_costs, 4),
            tax=round(total_tax, 4),
            fcf_non_risk_adj=round(total_fcf, 4),
            risk_multiplier=1.0,  # Not meaningful for total
            fcf_risk_adj=round(total_fcf_ra, 4),
            fcf_pv=round(total_pv, 4),
        ))

    db.flush()


