"""
PharmaPulse — Monte Carlo Simulation Engine

Runs N iterations of NPV calculation with randomized inputs.

Process per iteration (from Spec Section 7):
    1. Draw one scenario per region based on scenario probabilities
    2. Apply MC shocks for active variables:
       - Commercial 3-point: multiplicative shocks to base values
       - Bernoulli events: absolute overrides when event triggers
       - R&D shocks: SR overrides, duration changes, cost multipliers
    3. If phase duration changed:
       a. Shift following phase start/end dates
       b. Re-bucket phase costs across new calendar years
       c. Shift commercial launch dates (same as approval shift)
       d. LOE does NOT move
    4. Calculate risk-adjusted NPV for this iteration
    5. Store iteration NPV

After all iterations:
    - Compute average, P10, P25, P50, P75, P90
    - Store results on snapshot record
"""

import json
import math
import copy
from collections import defaultdict
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from ..models import (
    Asset, Snapshot, PhaseInput, RDCost, CommercialRow,
    MCCommercialConfig, MCRDConfig, Cashflow,
)
from .risk_adjustment import (
    PHASE_ORDER, compute_cumulative_pos,
    get_phase_cost_multiplier, get_commercial_multiplier,
)
from .revenue_curves import compute_annual_revenue, compute_peak_revenue_for_row
from .discounting import discount_cashflow


def run_monte_carlo(snapshot_id: int, db: Session) -> dict:
    """
    Main entry point for Monte Carlo simulation.

    Args:
        snapshot_id: ID of the snapshot to simulate.
        db: SQLAlchemy session.

    Returns:
        Dict with average_npv, percentiles, distribution array, iteration count.
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

    # Load MC config
    mc_commercial = (
        db.query(MCCommercialConfig)
        .filter(MCCommercialConfig.snapshot_id == snapshot_id)
        .first()
    )

    mc_rd_configs = (
        db.query(MCRDConfig)
        .filter(MCRDConfig.snapshot_id == snapshot_id)
        .all()
    )

    # ------------------------------------------------------------------
    # 2. Prepare base data
    # ------------------------------------------------------------------
    n_iterations = snapshot.mc_iterations or 1000
    seed = snapshot.random_seed or 42
    rng = np.random.default_rng(seed)

    valuation_year = snapshot.valuation_year
    horizon_end = valuation_year + snapshot.horizon_years
    current_phase = asset.current_phase
    current_phase_idx = PHASE_ORDER.index(current_phase) if current_phase in PHASE_ORDER else 0

    # Pre-compute base peak revenues per commercial row
    base_peaks = {}
    for row in commercial_rows:
        base_peaks[row.id] = compute_peak_revenue_for_row(row)

    # Group commercial rows by (region, scenario)
    region_scenario_groups = defaultdict(list)
    for row in commercial_rows:
        region_scenario_groups[(row.region, row.scenario)].append(row)

    # Get unique regions and their scenarios with probabilities
    region_scenarios = defaultdict(list)
    for (region, scenario), rows in region_scenario_groups.items():
        prob = rows[0].scenario_probability
        region_scenarios[region].append((scenario, prob))

    # Build base phase data
    base_phases = []
    for pi in phase_inputs:
        base_phases.append({
            "phase_name": pi.phase_name,
            "start_date": pi.start_date,
            "success_rate": pi.success_rate,
        })

    # Build base R&D cost data  
    base_rd_costs = []
    for c in rd_costs:
        base_rd_costs.append({
            "year": c.year,
            "phase_name": c.phase_name,
            "rd_cost": c.rd_cost,
        })

    # Parse MC R&D configs into a lookup
    rd_config_map = {}  # {(phase_name, variable): config}
    for cfg in mc_rd_configs:
        rd_config_map[(cfg.phase_name, cfg.variable)] = cfg

    # ------------------------------------------------------------------
    # 3. Run iterations
    # ------------------------------------------------------------------
    npv_distribution = []

    for iteration in range(n_iterations):
        iter_npv = _run_single_iteration(
            rng=rng,
            base_phases=base_phases,
            base_rd_costs=base_rd_costs,
            commercial_rows=commercial_rows,
            base_peaks=base_peaks,
            region_scenario_groups=region_scenario_groups,
            region_scenarios=region_scenarios,
            mc_commercial=mc_commercial,
            rd_config_map=rd_config_map,
            current_phase=current_phase,
            current_phase_idx=current_phase_idx,
            valuation_year=valuation_year,
            horizon_end=horizon_end,
            wacc_rd=snapshot.wacc_rd,
            approval_date=snapshot.approval_date,
        )
        npv_distribution.append(iter_npv)

    # ------------------------------------------------------------------
    # 4. Compute statistics
    # ------------------------------------------------------------------
    npv_array = np.array(npv_distribution)
    avg_npv = float(np.mean(npv_array))
    p10 = float(np.percentile(npv_array, 10))
    p25 = float(np.percentile(npv_array, 25))
    p50 = float(np.percentile(npv_array, 50))
    p75 = float(np.percentile(npv_array, 75))
    p90 = float(np.percentile(npv_array, 90))
    std_dev = float(np.std(npv_array))

    # ------------------------------------------------------------------
    # 5. Update snapshot record
    # ------------------------------------------------------------------
    snapshot.npv_mc_average = round(avg_npv, 2)
    snapshot.npv_mc_p10 = round(p10, 2)
    snapshot.npv_mc_p25 = round(p25, 2)
    snapshot.npv_mc_p50 = round(p50, 2)
    snapshot.npv_mc_p75 = round(p75, 2)
    snapshot.npv_mc_p90 = round(p90, 2)

    # Store distribution as JSON (downsample if very large)
    distribution_list = [round(float(x), 2) for x in npv_array]
    snapshot.mc_distribution_json = json.dumps(distribution_list)

    db.commit()

    # ------------------------------------------------------------------
    # 6. Return results
    # ------------------------------------------------------------------
    return {
        "snapshot_id": snapshot_id,
        "iterations": n_iterations,
        "random_seed": seed,
        "average_npv": round(avg_npv, 2),
        "std_dev": round(std_dev, 2),
        "percentiles": {
            "p10": round(p10, 2),
            "p25": round(p25, 2),
            "p50": round(p50, 2),
            "p75": round(p75, 2),
            "p90": round(p90, 2),
        },
        "distribution": distribution_list,
    }


# ===========================================================================
# SINGLE ITERATION
# ===========================================================================

def _run_single_iteration(
    rng: np.random.Generator,
    base_phases: list,
    base_rd_costs: list,
    commercial_rows: list,
    base_peaks: dict,
    region_scenario_groups: dict,
    region_scenarios: dict,
    mc_commercial: Optional[MCCommercialConfig],
    rd_config_map: dict,
    current_phase: str,
    current_phase_idx: int,
    valuation_year: int,
    horizon_end: int,
    wacc_rd: float,
    approval_date: float,
) -> float:
    """
    Runs a single Monte Carlo iteration and returns the NPV.
    """
    # ------- Draw scenario per region -------
    chosen_scenarios = {}  # region -> scenario_name
    for region, scenarios in region_scenarios.items():
        probs = [s[1] for s in scenarios]
        total = sum(probs)
        if total > 0:
            normalized = [p / total for p in probs]
            idx = rng.choice(len(scenarios), p=normalized)
            chosen_scenarios[region] = scenarios[idx][0]
        else:
            chosen_scenarios[region] = scenarios[0][0]

    # ------- Apply R&D shocks -------
    # Deep copy phases for this iteration
    iter_phases = copy.deepcopy(base_phases)
    iter_rd_costs = copy.deepcopy(base_rd_costs)

    # SR shocks
    sr_overrides = {}
    for phase_data in iter_phases:
        phase_name = phase_data["phase_name"]
        key = (phase_name, "success_rate")
        if key in rd_config_map:
            cfg = rd_config_map[key]
            if cfg.toggle == "Included":
                shock = _draw_3point_shock(rng, cfg)
                sr_overrides[phase_name] = shock  # Absolute override

    # Duration shocks
    total_shift_years = 0.0
    for phase_data in iter_phases:
        phase_name = phase_data["phase_name"]
        key = (phase_name, "duration")
        if key in rd_config_map:
            cfg = rd_config_map[key]
            if cfg.toggle == "Included":
                shock_months = _draw_3point_shock(rng, cfg)
                if shock_months != 0:
                    total_shift_years += shock_months / 12.0

    # R&D cost shocks  
    rd_cost_multipliers = {}
    for phase_data in iter_phases:
        phase_name = phase_data["phase_name"]
        key = (phase_name, "cost")
        if key in rd_config_map:
            cfg = rd_config_map[key]
            if cfg.toggle == "Included":
                mult = _draw_3point_shock(rng, cfg)
                rd_cost_multipliers[phase_name] = mult

    # ------- Apply commercial shocks -------
    commercial_shocks = _draw_commercial_shocks(rng, mc_commercial, region_scenarios)

    # ------- Compute risk adjustment -------
    pos_result = compute_cumulative_pos(iter_phases, current_phase, sr_overrides)
    commercial_multiplier = get_commercial_multiplier(pos_result)

    # ------- Calculate R&D NPV -------
    npv_rd = 0.0
    for cost_data in iter_rd_costs:
        if cost_data["year"] < valuation_year:
            continue
        cost_phase_idx = PHASE_ORDER.index(cost_data["phase_name"]) if cost_data["phase_name"] in PHASE_ORDER else -1
        if cost_phase_idx < current_phase_idx:
            continue

        cost_multiplier = get_phase_cost_multiplier(pos_result, cost_data["phase_name"])
        rd_cost = cost_data["rd_cost"]

        # Apply R&D cost shock multiplier
        if cost_data["phase_name"] in rd_cost_multipliers:
            rd_cost *= rd_cost_multipliers[cost_data["phase_name"]]

        risk_adj = rd_cost * cost_multiplier
        pv = discount_cashflow(risk_adj, cost_data["year"], valuation_year, wacc_rd)
        npv_rd += pv

    # ------- Calculate commercial NPV -------
    npv_commercial = 0.0

    for region, scenario_name in chosen_scenarios.items():
        key = (region, scenario_name)
        if key not in region_scenario_groups:
            continue

        rows = region_scenario_groups[key]
        wacc_region = rows[0].wacc_region

        # Compute revenue for each year
        for year in range(valuation_year, horizon_end + 1):
            year_revenue = 0.0

            for row in rows:
                # Get base peak revenue
                peak = base_peaks.get(row.id, 0)

                # Apply commercial shocks
                shock_key = (region, scenario_name)
                pop_mult = commercial_shocks.get(("target_population", shock_key), 1.0)
                ms_mult = commercial_shocks.get(("market_share", shock_key), 1.0)
                ttp_mult = commercial_shocks.get(("time_to_peak", shock_key), 1.0)
                price_mult = commercial_shocks.get(("gross_price", shock_key), 1.0)

                # Bernoulli events (absolute overrides)
                price_override = commercial_shocks.get(("price_event", shock_key), None)
                ms_override = commercial_shocks.get(("market_share_event", shock_key), None)

                # Adjust peak revenue with population and price shocks
                adjusted_peak = peak * pop_mult * price_mult
                if ms_override is not None:
                    # Market share event: recalculate peak with override
                    adjusted_peak = _recalc_peak_with_ms(row, ms_override) * pop_mult * price_mult
                else:
                    adjusted_peak = peak * pop_mult * ms_mult * price_mult

                if price_override is not None:
                    adjusted_peak = _recalc_peak_with_price(row, price_override) * pop_mult * ms_mult

                # Adjust time to peak
                effective_ttp = row.time_to_peak * ttp_mult

                # Shift launch date if duration shifts
                effective_launch = row.launch_date + total_shift_years

                seg_rev = compute_annual_revenue(
                    peak_revenue=adjusted_peak,
                    launch_date=effective_launch,
                    time_to_peak=effective_ttp,
                    plateau_years=row.plateau_years,
                    loe_year=row.loe_year,  # LOE does NOT move
                    loe_cliff_rate=row.loe_cliff_rate,
                    erosion_floor_pct=row.erosion_floor_pct,
                    years_to_erosion_floor=row.years_to_erosion_floor,
                    revenue_curve_type=row.revenue_curve_type,
                    logistic_k=row.logistic_k or 5.5,
                    logistic_midpoint=row.logistic_midpoint or 0.5,
                    year=year,
                )
                year_revenue += seg_rev

            if year_revenue <= 0:
                continue

            # FCF calculation
            rep_row = rows[0]
            cogs = year_revenue * rep_row.cogs_rate
            distribution = year_revenue * rep_row.distribution_rate
            operating = year_revenue * rep_row.operating_cost_rate
            ebit = year_revenue - cogs - distribution - operating
            tax = max(0, ebit * rep_row.tax_rate)
            fcf = ebit - tax

            fcf_risk_adj = fcf * commercial_multiplier
            pv = discount_cashflow(fcf_risk_adj, year, valuation_year, wacc_region)
            npv_commercial += pv

    return npv_rd + npv_commercial


# ===========================================================================
# SHOCK DRAWING FUNCTIONS
# ===========================================================================

def _draw_3point_shock(rng: np.random.Generator, cfg) -> float:
    """
    Draws a 3-point discrete random variable.
    
    Three outcomes: low, base (1.0), high
    Probabilities: low_prob, (1 - low_prob - high_prob), high_prob
    """
    low_val = cfg.min_value if cfg.min_value is not None else 1.0
    low_prob = cfg.min_probability if cfg.min_probability is not None else 0.0
    high_val = cfg.max_value if cfg.max_value is not None else 1.0
    high_prob = cfg.max_probability if cfg.max_probability is not None else 0.0

    base_prob = max(0, 1.0 - low_prob - high_prob)

    draw = rng.random()
    if draw < low_prob:
        return low_val
    elif draw < low_prob + base_prob:
        return 1.0  # Base case (no shock)
    else:
        return high_val


def _draw_commercial_shocks(
    rng: np.random.Generator,
    mc_commercial: Optional[MCCommercialConfig],
    region_scenarios: dict,
) -> dict:
    """
    Draws all commercial MC shocks for this iteration based on toggle settings.
    
    Returns dict of {(variable_name, (region, scenario)): shock_value}
    """
    shocks = {}
    if mc_commercial is None:
        return shocks

    # Define the 3-point variables and their config fields
    three_point_vars = [
        ("target_population", mc_commercial.use_target_population,
         mc_commercial.low_target_population, mc_commercial.low_target_population_prob,
         mc_commercial.high_target_population, mc_commercial.high_target_population_prob),
        ("market_share", mc_commercial.use_market_share,
         mc_commercial.low_market_share, mc_commercial.low_market_share_prob,
         mc_commercial.high_market_share, mc_commercial.high_market_share_prob),
        ("time_to_peak", mc_commercial.use_time_to_peak,
         mc_commercial.low_time_to_peak, mc_commercial.low_time_to_peak_prob,
         mc_commercial.high_time_to_peak, mc_commercial.high_time_to_peak_prob),
        ("gross_price", mc_commercial.use_gross_price,
         mc_commercial.low_gross_price, mc_commercial.low_gross_price_prob,
         mc_commercial.high_gross_price, mc_commercial.high_gross_price_prob),
    ]

    for var_name, toggle, low_val, low_prob, high_val, high_prob in three_point_vars:
        if toggle == "Not included":
            continue

        # Draw shocks based on correlation toggle
        _apply_correlation_shocks(
            rng, shocks, var_name, toggle,
            low_val or 1.0, low_prob or 0.0,
            high_val or 1.0, high_prob or 0.0,
            region_scenarios,
        )

    # Bernoulli events
    if mc_commercial.use_price_event != "Not included":
        _apply_bernoulli_shocks(
            rng, shocks, "price_event",
            mc_commercial.use_price_event,
            mc_commercial.price_event_value,
            mc_commercial.price_event_prob or 0.0,
            region_scenarios,
        )

    if mc_commercial.use_market_share_event != "Not included":
        _apply_bernoulli_shocks(
            rng, shocks, "market_share_event",
            mc_commercial.use_market_share_event,
            mc_commercial.market_share_event_value,
            mc_commercial.market_share_event_prob or 0.0,
            region_scenarios,
        )

    return shocks


def _apply_correlation_shocks(
    rng, shocks, var_name, toggle,
    low_val, low_prob, high_val, high_prob,
    region_scenarios,
):
    """Apply 3-point shocks with correlation rules."""

    def _draw():
        base_prob = max(0, 1.0 - low_prob - high_prob)
        draw = rng.random()
        if draw < low_prob:
            return low_val
        elif draw < low_prob + base_prob:
            return 1.0
        else:
            return high_val

    if toggle == "Same for all regions and scenarios":
        shock = _draw()
        for region, scenarios in region_scenarios.items():
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = shock

    elif toggle == "Same for all scenarios within the same region":
        for region, scenarios in region_scenarios.items():
            shock = _draw()
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = shock

    elif toggle == "Same for all regions within the same scenario":
        # Get unique scenario names
        all_scenarios = set()
        for scenarios in region_scenarios.values():
            for scen_name, _ in scenarios:
                all_scenarios.add(scen_name)
        scenario_shocks = {s: _draw() for s in all_scenarios}
        for region, scenarios in region_scenarios.items():
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = scenario_shocks[scen_name]

    else:  # "Independent"
        for region, scenarios in region_scenarios.items():
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = _draw()


def _apply_bernoulli_shocks(
    rng, shocks, var_name, toggle,
    event_value, event_prob, region_scenarios,
):
    """Apply Bernoulli event shocks."""
    if event_value is None:
        return

    def _draw():
        return event_value if rng.random() < event_prob else None

    if toggle == "Same for all regions and scenarios":
        result = _draw()
        for region, scenarios in region_scenarios.items():
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = result

    elif toggle == "Same for all scenarios within the same region":
        for region, scenarios in region_scenarios.items():
            result = _draw()
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = result

    else:  # Independent or by scenario
        for region, scenarios in region_scenarios.items():
            for scen_name, _ in scenarios:
                shocks[(var_name, (region, scen_name))] = _draw()


# ===========================================================================
# HELPER FUNCTIONS
# ===========================================================================

def _recalc_peak_with_ms(row, new_market_share: float) -> float:
    """Recalculate peak revenue with an overridden market share."""
    eligible = (
        row.patient_population * row.epi_f1 * row.epi_f2 *
        row.epi_f3 * row.epi_f4 * row.epi_f5 * row.epi_f6
    )
    treated = eligible * row.access_rate * new_market_share
    annual = treated * row.units_per_treatment * row.treatments_per_year * row.compliance_rate
    revenue_eur = annual * row.gross_price_per_treatment * row.gross_to_net_price_rate
    return revenue_eur / 1_000_000.0


def _recalc_peak_with_price(row, new_price: float) -> float:
    """Recalculate peak revenue with an overridden gross price."""
    eligible = (
        row.patient_population * row.epi_f1 * row.epi_f2 *
        row.epi_f3 * row.epi_f4 * row.epi_f5 * row.epi_f6
    )
    treated = eligible * row.access_rate * row.market_share
    annual = treated * row.units_per_treatment * row.treatments_per_year * row.compliance_rate
    revenue_eur = annual * new_price * row.gross_to_net_price_rate
    return revenue_eur / 1_000_000.0


