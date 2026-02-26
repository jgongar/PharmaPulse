"""
PharmaPulse — Family E: BD Cut & Reinvest Engine

Provides Business Development (BD) deal modeling and reinvestment analysis:
  - BD Deal Valuation:    Value an external asset acquisition (buy-side)
  - BD Cut Analysis:      Evaluate dropping an existing project for BD acquisition
  - Reinvest Comparison:  Side-by-side comparison of current vs BD replacement
  - Portfolio BD Scan:    Find portfolio projects that could be replaced by BD targets
"""

from functools import reduce
import operator

from sqlalchemy.orm import Session

from ..models import Portfolio
from .. import crud


def _compute_pts(snapshot) -> float:
    """Compute overall PTS as product of all phase success rates."""
    if not snapshot or not snapshot.phase_inputs:
        return 0.0
    return reduce(operator.mul, (pi.success_rate for pi in snapshot.phase_inputs), 1.0)


# ---------------------------------------------------------------------------
# BD DEAL VALUATION
# ---------------------------------------------------------------------------

def value_bd_deal(
    peak_sales_eur_mm: float,
    market_share_pct: float,
    margin_pct: float,
    years_to_launch: int,
    commercial_duration_years: int,
    upfront_eur_mm: float,
    milestones_eur_mm: float,
    royalty_pct: float = 0.0,
    wacc: float = 0.10,
    pts: float = 0.5,
) -> dict:
    """Value a BD deal (in-licensing or acquisition)."""
    share = market_share_pct / 100
    margin = margin_pct / 100
    royalty = royalty_pct / 100

    annual_revenue = peak_sales_eur_mm * share * margin * (1 - royalty)

    total_commercial_pv = 0.0
    yearly_cashflows = []

    for y in range(1, commercial_duration_years + 1):
        year_from_now = years_to_launch + y

        if y <= 2:
            rev_factor = y / 3.0
        elif y >= commercial_duration_years - 1:
            rev_factor = (commercial_duration_years - y + 1) / 3.0
        else:
            rev_factor = 1.0

        revenue = annual_revenue * max(rev_factor, 0)
        pv = revenue / ((1 + wacc) ** year_from_now)
        total_commercial_pv += pv

        yearly_cashflows.append({
            "year_from_launch": y,
            "year_from_now": year_from_now,
            "revenue_eur_mm": round(revenue, 2),
            "pv_eur_mm": round(pv, 2),
        })

    risk_adjusted_pv = total_commercial_pv * pts
    total_cost = upfront_eur_mm + milestones_eur_mm
    deal_npv = risk_adjusted_pv - total_cost
    roi = (risk_adjusted_pv / total_cost - 1) * 100 if total_cost > 0 else 0

    return {
        "deal_parameters": {
            "peak_sales_eur_mm": peak_sales_eur_mm,
            "market_share_pct": market_share_pct,
            "margin_pct": margin_pct,
            "years_to_launch": years_to_launch,
            "commercial_duration_years": commercial_duration_years,
            "upfront_eur_mm": upfront_eur_mm,
            "milestones_eur_mm": milestones_eur_mm,
            "royalty_pct": royalty_pct,
            "wacc": wacc,
            "pts": pts,
        },
        "valuation": {
            "gross_commercial_pv": round(total_commercial_pv, 2),
            "risk_adjusted_pv": round(risk_adjusted_pv, 2),
            "total_cost": round(total_cost, 2),
            "deal_npv": round(deal_npv, 2),
            "roi_pct": round(roi, 1),
        },
        "yearly_cashflows": yearly_cashflows,
        "recommendation": (
            f"Deal NPV: {deal_npv:,.1f} EUR mm (ROI: {roi:.0f}%). "
            + (
                "Deal is value-accretive. Consider proceeding."
                if deal_npv > 0
                else "Deal destroys value at current terms. Negotiate or walk away."
            )
        ),
    }


# ---------------------------------------------------------------------------
# BD CUT & REINVEST
# ---------------------------------------------------------------------------

def analyze_bd_cut_reinvest(
    portfolio_id: int,
    cut_asset_id: int,
    bd_deal_params: dict,
    db: Session,
) -> dict:
    """Compare: cut an existing project and replace with a BD deal."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    cut_project = None
    for proj in portfolio.projects:
        if proj.asset_id == cut_asset_id:
            cut_project = proj
            break

    if not cut_project:
        raise ValueError(f"Asset {cut_asset_id} not in portfolio {portfolio_id}")

    cut_asset = cut_project.asset
    cut_snapshot = cut_project.snapshot

    current_npv = (cut_snapshot.npv_deterministic or 0) if cut_snapshot else 0
    current_pts = _compute_pts(cut_snapshot)
    current_rd_cost = (
        sum(abs(rc.rd_cost) for rc in cut_snapshot.rd_costs)
        if cut_snapshot else 0
    )

    bd_valuation = value_bd_deal(**bd_deal_params)
    bd_npv = bd_valuation["valuation"]["deal_npv"]
    bd_cost = bd_valuation["valuation"]["total_cost"]

    npv_delta = bd_npv - current_npv
    cost_delta = bd_cost - current_rd_cost
    budget_freed = current_rd_cost
    net_budget_impact = budget_freed - bd_cost

    return {
        "portfolio_id": portfolio_id,
        "current_project": {
            "asset_id": cut_asset_id,
            "compound_name": cut_asset.compound_name,
            "therapeutic_area": cut_asset.therapeutic_area,
            "current_phase": cut_asset.current_phase,
            "npv": round(current_npv, 2),
            "pts": round(current_pts, 3),
            "rd_cost": round(current_rd_cost, 2),
        },
        "bd_deal": bd_valuation,
        "comparison": {
            "npv_delta": round(npv_delta, 2),
            "cost_delta": round(cost_delta, 2),
            "budget_freed": round(budget_freed, 2),
            "net_budget_impact": round(net_budget_impact, 2),
            "npv_improvement": npv_delta > 0,
            "cost_savings": cost_delta < 0,
        },
        "recommendation": _bd_reinvest_recommendation(
            cut_asset.compound_name, current_npv, bd_npv, npv_delta,
            budget_freed, bd_cost,
        ),
    }


def _bd_reinvest_recommendation(
    cut_name: str, current_npv: float, bd_npv: float,
    delta: float, freed: float, bd_cost: float,
) -> str:
    if delta > 0 and bd_cost <= freed:
        return (
            f"Replacing {cut_name} (NPV: {current_npv:,.1f}) with BD deal "
            f"(NPV: {bd_npv:,.1f}) improves NPV by {delta:,.1f} EUR mm "
            f"and saves {freed - bd_cost:,.1f} EUR mm. Strongly recommended."
        )
    if delta > 0:
        return (
            f"BD deal improves NPV by {delta:,.1f} EUR mm but costs "
            f"{bd_cost - freed:,.1f} EUR mm more. Net positive if budget allows."
        )
    return (
        f"Current project {cut_name} has higher NPV ({current_npv:,.1f} vs "
        f"{bd_npv:,.1f}). BD swap loses {abs(delta):,.1f} EUR mm. Not recommended."
    )


# ---------------------------------------------------------------------------
# PORTFOLIO BD SCAN
# ---------------------------------------------------------------------------

def scan_bd_opportunities(
    portfolio_id: int,
    db: Session,
    min_npv_threshold: float = 0,
    max_pts_threshold: float = 1.0,
) -> dict:
    """Scan portfolio for projects that might be candidates for BD replacement."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    candidates = []

    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot

        npv = (snapshot.npv_deterministic or 0) if snapshot else 0
        pts = _compute_pts(snapshot)
        rd_cost = (
            sum(abs(rc.rd_cost) for rc in snapshot.rd_costs) if snapshot else 0
        )

        cost_npv_ratio = rd_cost / abs(npv) if npv != 0 else float("inf")

        flags = []
        if npv < min_npv_threshold:
            flags.append(f"Low NPV ({npv:,.1f} < {min_npv_threshold:,.1f})")
        if pts < max_pts_threshold:
            flags.append(f"Low PTS ({pts:.1%} < {max_pts_threshold:.0%})")
        if cost_npv_ratio > 0.5 and npv > 0:
            flags.append(f"High cost/NPV ratio ({cost_npv_ratio:.2f})")
        if npv <= 0:
            flags.append("Negative/zero NPV - value-destroying")

        if flags:
            candidates.append({
                "asset_id": asset.id,
                "compound_name": asset.compound_name,
                "therapeutic_area": asset.therapeutic_area,
                "current_phase": asset.current_phase,
                "npv": round(npv, 2),
                "pts": round(pts, 3),
                "rd_cost": round(rd_cost, 2),
                "cost_npv_ratio": round(cost_npv_ratio, 2)
                if cost_npv_ratio != float("inf") else "inf",
                "flags": flags,
                "flag_count": len(flags),
                "bd_replacement_priority": _bd_priority(npv, pts, cost_npv_ratio),
            })

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    candidates.sort(
        key=lambda x: priority_order.get(x["bd_replacement_priority"], 3)
    )

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_projects": len(portfolio.projects),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "filters_applied": {
            "min_npv_threshold": min_npv_threshold,
            "max_pts_threshold": max_pts_threshold,
        },
    }


def _bd_priority(npv: float, pts: float, ratio: float) -> str:
    if npv <= 0:
        return "HIGH"
    if pts < 0.2 or ratio > 1.0:
        return "HIGH"
    if pts < 0.4 or ratio > 0.5:
        return "MEDIUM"
    return "LOW"
