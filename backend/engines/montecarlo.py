"""Monte Carlo simulation engine."""

import numpy as np
from sqlalchemy.orm import Session

from .. import models
from .discounting import mid_year_discount_factor
from .risk_adjustment import cumulative_pos, total_pos
from .revenue_curves import get_revenue


def run_monte_carlo(db: Session, snapshot: models.Snapshot) -> dict:
    """Run MC simulation on a snapshot. Returns statistics."""
    mc = snapshot.mc_config
    n_iter = mc.n_iterations if mc else 10000
    peak_std = mc.peak_sales_std_pct if mc else 0.20
    delay_std = mc.launch_delay_std_years if mc else 1.0
    pos_var = mc.pos_variation_pct if mc else 0.10
    seed = mc.seed if mc else None

    rng = np.random.default_rng(seed)

    phase_dicts = [
        {
            "phase_name": pi.phase_name,
            "probability_of_success": pi.probability_of_success,
            "duration_years": pi.duration_years,
            "start_year": pi.start_year,
        }
        for pi in snapshot.phase_inputs
    ]
    rd_dict = {rc.year: rc.cost_usd_m for rc in snapshot.rd_costs}

    base_peak = snapshot.peak_sales_usd_m
    base_launch = snapshot.launch_year

    # Determine year range
    all_years = set()
    for pi in snapshot.phase_inputs:
        all_years.add(pi.start_year)
    for rc in snapshot.rd_costs:
        all_years.add(rc.year)
    commercial_end = snapshot.patent_expiry_year + 5  # extra buffer for delays
    for y in range(snapshot.launch_year - 2, commercial_end + 1):
        all_years.add(y)
    if not all_years:
        all_years = {2025}

    min_year = min(all_years)
    max_year = max(all_years)
    base_year = min_year

    npvs = np.zeros(n_iter)

    for i in range(n_iter):
        # Sample parameters
        sim_peak = max(base_peak * (1 + rng.normal(0, peak_std)), 0)
        sim_delay = int(round(rng.normal(0, delay_std)))
        sim_launch = base_launch + sim_delay
        sim_expiry = snapshot.patent_expiry_year + sim_delay

        # Perturb POS
        sim_phases = []
        for pd in phase_dicts:
            perturbed_pos = pd["probability_of_success"] * (1 + rng.normal(0, pos_var))
            perturbed_pos = max(0.01, min(perturbed_pos, 1.0))
            sim_phases.append({**pd, "probability_of_success": perturbed_pos})

        running_npv = 0.0
        for year in range(min_year, max_year + 1):
            rd_cost = rd_dict.get(year, 0.0)
            gross_rev = get_revenue(
                year, sim_launch, sim_expiry,
                sim_peak, snapshot.time_to_peak_years,
                snapshot.generic_erosion_pct, snapshot.uptake_curve,
            )
            cogs = gross_rev * snapshot.cogs_pct
            sga = gross_rev * snapshot.sga_pct
            op_profit = gross_rev - cogs - sga
            tax = max(op_profit * snapshot.tax_rate, 0)
            commercial_cf = op_profit - tax
            net_cf = commercial_cf - rd_cost

            cum_pos = cumulative_pos(sim_phases, year)
            risk_adj = net_cf * cum_pos
            df = mid_year_discount_factor(year, base_year, snapshot.discount_rate)
            running_npv += risk_adj * df

        npvs[i] = running_npv

    return {
        "snapshot_id": snapshot.id,
        "mean_npv": round(float(np.mean(npvs)), 2),
        "median_npv": round(float(np.median(npvs)), 2),
        "std_npv": round(float(np.std(npvs)), 2),
        "p5": round(float(np.percentile(npvs, 5)), 2),
        "p25": round(float(np.percentile(npvs, 25)), 2),
        "p75": round(float(np.percentile(npvs, 75)), 2),
        "p95": round(float(np.percentile(npvs, 95)), 2),
        "prob_positive": round(float(np.mean(npvs > 0)), 4),
        "n_iterations": n_iter,
        "histogram_data": [round(float(x), 2) for x in npvs[::max(1, n_iter // 200)]],
    }
