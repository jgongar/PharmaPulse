"""
PharmaPulse — Family B: TA Budget Reallocation Engine

Provides tools for analyzing therapeutic area (TA) level budget shifts:
  - TA Summary:        Aggregate NPV, cost, project count per TA
  - Budget Shift:      Move X EUR mm from one TA to another — impact analysis
  - Optimal Mix:       Rank TAs by efficiency (NPV per EUR mm R&D cost)
"""

from functools import reduce
import operator

from sqlalchemy.orm import Session

from ..models import Portfolio, PortfolioProject, Snapshot, Cashflow
from .. import crud


def _compute_pts(snapshot) -> float:
    """Compute overall PTS as product of all phase success rates."""
    if not snapshot.phase_inputs:
        return 0.0
    return reduce(operator.mul, (pi.success_rate for pi in snapshot.phase_inputs), 1.0)


# ---------------------------------------------------------------------------
# TA AGGREGATION
# ---------------------------------------------------------------------------

def get_ta_summary(portfolio_id: int, db: Session) -> dict:
    """Aggregate portfolio data by therapeutic area."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    ta_data: dict[str, dict] = {}

    phase_order = {
        "Phase 1": 1, "Phase 2": 2, "Phase 2 B": 3,
        "Phase 3": 4, "Registration": 5, "Approved": 6,
    }

    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot
        ta = asset.therapeutic_area or "Unknown"

        if ta not in ta_data:
            ta_data[ta] = {
                "therapeutic_area": ta,
                "project_count": 0,
                "project_names": [],
                "total_npv": 0.0,
                "total_rd_cost": 0.0,
                "phases": [],
                "pts_values": [],
            }

        entry = ta_data[ta]
        entry["project_count"] += 1
        entry["project_names"].append(asset.compound_name)

        if snapshot:
            npv = snapshot.npv_deterministic or 0.0
            entry["total_npv"] += npv

            rd_total = sum(abs(rc.rd_cost) for rc in snapshot.rd_costs)
            entry["total_rd_cost"] += rd_total

            phase_num = phase_order.get(asset.current_phase, 0)
            entry["phases"].append(phase_num)

            pts = _compute_pts(snapshot)
            if pts > 0:
                entry["pts_values"].append(pts)

    results = []
    for ta, data in ta_data.items():
        npv = data["total_npv"]
        cost = data["total_rd_cost"]
        efficiency = npv / cost if cost > 0 else 0.0
        avg_phase = (
            sum(data["phases"]) / len(data["phases"])
            if data["phases"] else 0
        )
        avg_pts = (
            sum(data["pts_values"]) / len(data["pts_values"])
            if data["pts_values"] else 0
        )

        results.append({
            "therapeutic_area": ta,
            "project_count": data["project_count"],
            "project_names": data["project_names"],
            "total_npv": round(npv, 2),
            "total_rd_cost": round(cost, 2),
            "npv_per_eur_mm": round(efficiency, 2),
            "avg_phase_index": round(avg_phase, 1),
            "avg_pts": round(avg_pts, 3),
        })

    results.sort(key=lambda x: x["npv_per_eur_mm"], reverse=True)

    portfolio_total_npv = sum(r["total_npv"] for r in results)
    portfolio_total_cost = sum(r["total_rd_cost"] for r in results)

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "portfolio_total_npv": round(portfolio_total_npv, 2),
        "portfolio_total_rd_cost": round(portfolio_total_cost, 2),
        "ta_count": len(results),
        "ta_summaries": results,
    }


# ---------------------------------------------------------------------------
# BUDGET SHIFT ANALYSIS
# ---------------------------------------------------------------------------

def analyze_budget_shift(
    portfolio_id: int,
    source_ta: str,
    target_ta: str,
    shift_amount_eur_mm: float,
    db: Session,
) -> dict:
    """Analyze the impact of shifting R&D budget from one TA to another."""
    summary = get_ta_summary(portfolio_id, db)

    source_data = None
    target_data = None
    for ta in summary["ta_summaries"]:
        if ta["therapeutic_area"].lower() == source_ta.lower():
            source_data = ta
        if ta["therapeutic_area"].lower() == target_ta.lower():
            target_data = ta

    if not source_data:
        raise ValueError(f"Therapeutic area '{source_ta}' not found in portfolio")
    if not target_data:
        raise ValueError(f"Therapeutic area '{target_ta}' not found in portfolio")

    if shift_amount_eur_mm <= 0:
        raise ValueError("Shift amount must be positive")
    if shift_amount_eur_mm > source_data["total_rd_cost"]:
        raise ValueError(
            f"Shift amount ({shift_amount_eur_mm}) exceeds source TA budget "
            f"({source_data['total_rd_cost']})"
        )

    source_cost = source_data["total_rd_cost"]
    source_npv = source_data["total_npv"]
    cut_fraction = shift_amount_eur_mm / source_cost if source_cost > 0 else 0
    npv_lost = source_npv * cut_fraction

    target_efficiency = target_data["npv_per_eur_mm"]
    marginal_efficiency = target_efficiency * 0.70
    npv_gained = shift_amount_eur_mm * marginal_efficiency

    net_npv_delta = npv_gained - npv_lost

    new_source_cost = source_cost - shift_amount_eur_mm
    new_source_npv = source_npv - npv_lost
    new_target_cost = target_data["total_rd_cost"] + shift_amount_eur_mm
    new_target_npv = target_data["total_npv"] + npv_gained

    return {
        "portfolio_id": portfolio_id,
        "shift_amount_eur_mm": round(shift_amount_eur_mm, 2),
        "source": {
            "therapeutic_area": source_data["therapeutic_area"],
            "current_rd_cost": round(source_cost, 2),
            "new_rd_cost": round(new_source_cost, 2),
            "current_npv": round(source_npv, 2),
            "npv_lost": round(npv_lost, 2),
            "new_npv": round(new_source_npv, 2),
            "efficiency_before": round(source_data["npv_per_eur_mm"], 2),
            "efficiency_after": round(
                new_source_npv / new_source_cost if new_source_cost > 0 else 0, 2
            ),
        },
        "target": {
            "therapeutic_area": target_data["therapeutic_area"],
            "current_rd_cost": round(target_data["total_rd_cost"], 2),
            "new_rd_cost": round(new_target_cost, 2),
            "current_npv": round(target_data["total_npv"], 2),
            "npv_gained": round(npv_gained, 2),
            "new_npv": round(new_target_npv, 2),
            "efficiency_before": round(target_efficiency, 2),
            "marginal_efficiency": round(marginal_efficiency, 2),
        },
        "net_impact": {
            "npv_delta": round(net_npv_delta, 2),
            "npv_delta_pct": round(
                (net_npv_delta / abs(summary["portfolio_total_npv"]) * 100)
                if summary["portfolio_total_npv"] != 0 else 0, 1
            ),
            "portfolio_npv_before": round(summary["portfolio_total_npv"], 2),
            "portfolio_npv_after": round(
                summary["portfolio_total_npv"] + net_npv_delta, 2
            ),
        },
        "recommendation": _budget_shift_recommendation(
            source_data["therapeutic_area"],
            target_data["therapeutic_area"],
            shift_amount_eur_mm, npv_lost, npv_gained, net_npv_delta,
        ),
    }


def _budget_shift_recommendation(
    source_ta: str, target_ta: str,
    amount: float, lost: float, gained: float, net: float,
) -> str:
    if net > 0:
        return (
            f"Shifting {amount:,.1f} EUR mm from {source_ta} to {target_ta}: "
            f"loses {lost:,.1f} EUR mm NPV, gains {gained:,.1f} EUR mm. "
            f"Net positive: +{net:,.1f} EUR mm. Recommendation: PROCEED."
        )
    return (
        f"Shifting {amount:,.1f} EUR mm from {source_ta} to {target_ta}: "
        f"loses {lost:,.1f} EUR mm NPV, gains {gained:,.1f} EUR mm. "
        f"Net negative: {net:,.1f} EUR mm. Recommendation: DO NOT SHIFT."
    )


# ---------------------------------------------------------------------------
# OPTIMAL MIX RANKING
# ---------------------------------------------------------------------------

def rank_ta_efficiency(portfolio_id: int, db: Session) -> dict:
    """Rank therapeutic areas by NPV efficiency and suggest optimal budget allocation."""
    summary = get_ta_summary(portfolio_id, db)
    ta_list = summary["ta_summaries"]

    total_budget = summary["portfolio_total_rd_cost"]
    if total_budget <= 0:
        return {
            "portfolio_id": portfolio_id,
            "message": "No R&D costs found in portfolio",
            "rankings": [],
        }

    total_efficiency = sum(max(ta["npv_per_eur_mm"], 0) for ta in ta_list)

    rankings = []
    for ta in ta_list:
        current_share = ta["total_rd_cost"] / total_budget if total_budget > 0 else 0
        eff = max(ta["npv_per_eur_mm"], 0)
        optimal_share = eff / total_efficiency if total_efficiency > 0 else 0
        optimal_budget = optimal_share * total_budget
        delta = optimal_budget - ta["total_rd_cost"]

        rankings.append({
            "therapeutic_area": ta["therapeutic_area"],
            "project_count": ta["project_count"],
            "total_npv": ta["total_npv"],
            "total_rd_cost": ta["total_rd_cost"],
            "npv_per_eur_mm": ta["npv_per_eur_mm"],
            "current_budget_share_pct": round(current_share * 100, 1),
            "optimal_budget_share_pct": round(optimal_share * 100, 1),
            "optimal_budget_eur_mm": round(optimal_budget, 2),
            "budget_delta_eur_mm": round(delta, 2),
            "action": (
                "INCREASE" if delta > 0.5 else
                "DECREASE" if delta < -0.5 else
                "MAINTAIN"
            ),
        })

    rankings.sort(key=lambda x: x["npv_per_eur_mm"], reverse=True)

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": summary["portfolio_name"],
        "total_rd_budget": round(total_budget, 2),
        "ta_count": len(rankings),
        "rankings": rankings,
        "insight": _efficiency_insight(rankings),
    }


def _efficiency_insight(rankings: list[dict]) -> str:
    if not rankings:
        return "No therapeutic areas to analyze."

    best = rankings[0]
    increases = [r for r in rankings if r["action"] == "INCREASE"]
    decreases = [r for r in rankings if r["action"] == "DECREASE"]

    parts = [
        f"Most efficient TA: {best['therapeutic_area']} "
        f"({best['npv_per_eur_mm']:.1f}x NPV per EUR mm)."
    ]
    if increases:
        names = ", ".join(r["therapeutic_area"] for r in increases)
        parts.append(f"Recommend increasing: {names}.")
    if decreases:
        names = ", ".join(r["therapeutic_area"] for r in decreases)
        parts.append(f"Recommend decreasing: {names}.")

    return " ".join(parts)
