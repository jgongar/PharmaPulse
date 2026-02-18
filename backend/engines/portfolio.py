"""Portfolio-level NPV aggregation and simulation engine.

Aggregates individual asset NPVs into portfolio-level metrics,
runs portfolio-level Monte Carlo with correlation support,
and computes portfolio optimization metrics.
"""

import numpy as np
from sqlalchemy.orm import Session

from .. import crud, models
from .deterministic import run_deterministic_npv
from .montecarlo import run_monte_carlo
from .risk_adjustment import total_pos
from .discounting import mid_year_discount_factor
from .revenue_curves import get_revenue


def portfolio_summary(db: Session, portfolio: models.Portfolio) -> dict:
    """Compute aggregate portfolio metrics from member snapshots."""
    members = portfolio.members
    if not members:
        return {
            "portfolio_id": portfolio.id,
            "name": portfolio.name,
            "num_assets": 0,
            "total_enpv_usd_m": 0,
            "assets": [],
        }

    asset_results = []
    total_enpv = 0.0

    for member in members:
        snapshot = crud.get_snapshot(db, member.snapshot_id)
        if not snapshot:
            continue

        # Run NPV if no cashflows exist
        if not snapshot.cashflows:
            run_deterministic_npv(db, snapshot)
            snapshot = crud.get_snapshot(db, member.snapshot_id)

        asset = crud.get_asset(db, snapshot.asset_id)
        cfs = snapshot.cashflows
        enpv = cfs[-1].cumulative_npv_usd_m if cfs else 0

        phase_dicts = [
            {"probability_of_success": pi.probability_of_success}
            for pi in snapshot.phase_inputs
        ]
        cum_pos = 1.0
        for pd in phase_dicts:
            cum_pos *= pd["probability_of_success"]

        asset_info = {
            "asset_id": snapshot.asset_id,
            "asset_name": asset.name if asset else f"Asset {snapshot.asset_id}",
            "snapshot_id": snapshot.id,
            "therapeutic_area": asset.therapeutic_area if asset else "",
            "current_phase": asset.current_phase if asset else "",
            "enpv_usd_m": round(enpv, 2),
            "cumulative_pos": round(cum_pos, 6),
            "peak_sales_usd_m": snapshot.peak_sales_usd_m,
            "launch_year": snapshot.launch_year,
            "patent_expiry_year": snapshot.patent_expiry_year,
        }
        asset_results.append(asset_info)
        total_enpv += enpv

    # Portfolio-level stats
    enpvs = [a["enpv_usd_m"] for a in asset_results]
    peak_sales = [a["peak_sales_usd_m"] for a in asset_results]

    # Diversification by therapeutic area
    ta_counts = {}
    for a in asset_results:
        ta = a["therapeutic_area"]
        ta_counts[ta] = ta_counts.get(ta, 0) + 1

    # Phase distribution
    phase_counts = {}
    for a in asset_results:
        p = a["current_phase"]
        phase_counts[p] = phase_counts.get(p, 0) + 1

    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "num_assets": len(asset_results),
        "total_enpv_usd_m": round(total_enpv, 2),
        "mean_enpv_usd_m": round(np.mean(enpvs), 2) if enpvs else 0,
        "median_enpv_usd_m": round(float(np.median(enpvs)), 2) if enpvs else 0,
        "total_peak_sales_usd_m": round(sum(peak_sales), 2),
        "ta_distribution": ta_counts,
        "phase_distribution": phase_counts,
        "assets": asset_results,
    }


def portfolio_monte_carlo(db: Session, portfolio: models.Portfolio,
                          n_iterations: int = 10000,
                          correlation: float = 0.0,
                          seed: int | None = None) -> dict:
    """Run portfolio-level Monte Carlo simulation.

    Simulates all assets jointly, optionally with inter-asset correlation.
    Returns portfolio NPV distribution statistics.
    """
    members = portfolio.members
    if not members:
        return {"portfolio_id": portfolio.id, "error": "No assets in portfolio"}

    snapshots = []
    for member in members:
        snap = crud.get_snapshot(db, member.snapshot_id)
        if snap:
            snapshots.append(snap)

    if not snapshots:
        return {"portfolio_id": portfolio.id, "error": "No valid snapshots"}

    rng = np.random.default_rng(seed)
    n_assets = len(snapshots)

    # Generate correlated random factors if correlation > 0
    if correlation > 0 and n_assets > 1:
        cov_matrix = np.full((n_assets, n_assets), correlation)
        np.fill_diagonal(cov_matrix, 1.0)
        L = np.linalg.cholesky(cov_matrix)
    else:
        L = None

    portfolio_npvs = np.zeros(n_iterations)

    for i in range(n_iterations):
        # Generate random factors
        if L is not None:
            z = rng.standard_normal(n_assets)
            correlated_z = L @ z
        else:
            correlated_z = rng.standard_normal(n_assets)

        iter_total = 0.0

        for j, snapshot in enumerate(snapshots):
            mc = snapshot.mc_config
            peak_std = mc.peak_sales_std_pct if mc else 0.20
            delay_std = mc.launch_delay_std_years if mc else 1.0
            pos_var = mc.pos_variation_pct if mc else 0.10

            # Use correlated factor to drive peak sales variation
            sim_peak = max(snapshot.peak_sales_usd_m * (1 + peak_std * correlated_z[j]), 0)
            sim_delay = int(round(rng.normal(0, delay_std)))
            sim_launch = snapshot.launch_year + sim_delay
            sim_expiry = snapshot.patent_expiry_year + sim_delay

            phase_dicts = []
            for pi in snapshot.phase_inputs:
                perturbed_pos = pi.probability_of_success * (1 + rng.normal(0, pos_var))
                perturbed_pos = max(0.01, min(perturbed_pos, 1.0))
                phase_dicts.append({
                    "phase_name": pi.phase_name,
                    "probability_of_success": perturbed_pos,
                    "duration_years": pi.duration_years,
                    "start_year": pi.start_year,
                })

            rd_dict = {rc.year: rc.cost_usd_m for rc in snapshot.rd_costs}

            # Year range
            all_years = set()
            for pi in snapshot.phase_inputs:
                all_years.add(pi.start_year)
            for rc in snapshot.rd_costs:
                all_years.add(rc.year)
            for y in range(sim_launch - 2, sim_expiry + 4):
                all_years.add(y)
            if not all_years:
                continue

            min_year = min(all_years)
            max_year = max(all_years)
            base_year = min_year

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

                from .risk_adjustment import cumulative_pos
                cum_pos = cumulative_pos(phase_dicts, year)
                risk_adj = net_cf * cum_pos
                df = mid_year_discount_factor(year, base_year, snapshot.discount_rate)
                running_npv += risk_adj * df

            iter_total += running_npv

        portfolio_npvs[i] = iter_total

    return {
        "portfolio_id": portfolio.id,
        "name": portfolio.name,
        "n_iterations": n_iterations,
        "correlation": correlation,
        "num_assets": n_assets,
        "mean_npv": round(float(np.mean(portfolio_npvs)), 2),
        "median_npv": round(float(np.median(portfolio_npvs)), 2),
        "std_npv": round(float(np.std(portfolio_npvs)), 2),
        "p5": round(float(np.percentile(portfolio_npvs, 5)), 2),
        "p25": round(float(np.percentile(portfolio_npvs, 25)), 2),
        "p75": round(float(np.percentile(portfolio_npvs, 75)), 2),
        "p95": round(float(np.percentile(portfolio_npvs, 95)), 2),
        "prob_positive": round(float(np.mean(portfolio_npvs > 0)), 4),
        "histogram_data": [round(float(x), 2) for x in portfolio_npvs[::max(1, n_iterations // 200)]],
    }


def portfolio_cashflow_timeline(db: Session, portfolio: models.Portfolio) -> list[dict]:
    """Aggregate yearly cashflows across all portfolio assets."""
    members = portfolio.members
    yearly = {}

    for member in members:
        snapshot = crud.get_snapshot(db, member.snapshot_id)
        if not snapshot or not snapshot.cashflows:
            continue

        for cf in snapshot.cashflows:
            y = cf.year
            if y not in yearly:
                yearly[y] = {
                    "year": y,
                    "total_rd_cost_usd_m": 0,
                    "total_commercial_cf_usd_m": 0,
                    "total_net_cf_usd_m": 0,
                    "total_risk_adj_cf_usd_m": 0,
                    "total_pv_usd_m": 0,
                }
            yearly[y]["total_rd_cost_usd_m"] += cf.rd_cost_usd_m
            yearly[y]["total_commercial_cf_usd_m"] += cf.commercial_cf_usd_m
            yearly[y]["total_net_cf_usd_m"] += cf.net_cashflow_usd_m
            yearly[y]["total_risk_adj_cf_usd_m"] += cf.risk_adjusted_cf_usd_m
            yearly[y]["total_pv_usd_m"] += cf.pv_usd_m

    # Compute cumulative
    result = []
    cum_pv = 0.0
    for y in sorted(yearly.keys()):
        row = yearly[y]
        cum_pv += row["total_pv_usd_m"]
        row["cumulative_pv_usd_m"] = round(cum_pv, 2)
        for k in row:
            if k != "year" and k != "cumulative_pv_usd_m":
                row[k] = round(row[k], 2)
        result.append(row)

    return result
