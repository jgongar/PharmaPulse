"""
PharmaPulse — Family D: Innovation vs Risk Charter Engine

Provides strategic portfolio visualization and scoring:
  - Risk-Return Scatter:  Plot each project on an NPV vs PTS (risk) chart
  - Innovation Score:     Multi-factor scoring of portfolio innovation level
  - Charter Compliance:   Check portfolio against a strategic risk/innovation charter
  - Efficient Frontier:   Pareto-optimal projects on the risk-return plane
"""

from functools import reduce
import operator

from sqlalchemy.orm import Session

from ..models import Portfolio
from .. import crud


# Default charter targets
DEFAULT_CHARTER = {
    "min_innovation_score": 60,
    "target_portfolio_pts_pct": 40,
    "max_single_project_weight_pct": 30,
    "min_phase_diversity": 3,
}


def _compute_pts(snapshot) -> float:
    """Compute overall PTS as product of all phase success rates."""
    if not snapshot or not snapshot.phase_inputs:
        return 0.0
    return reduce(operator.mul, (pi.success_rate for pi in snapshot.phase_inputs), 1.0)


# ---------------------------------------------------------------------------
# RISK-RETURN DATA
# ---------------------------------------------------------------------------

def get_risk_return_scatter(portfolio_id: int, db: Session) -> dict:
    """Generate data for risk-return scatter plot."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    projects = []
    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot

        npv = (snapshot.npv_deterministic or 0) if snapshot else 0
        pts = _compute_pts(snapshot)
        peak_sales = asset.peak_sales_estimate or 0
        rd_cost = sum(abs(rc.rd_cost) for rc in snapshot.rd_costs) if snapshot else 0

        risk = 1.0 - pts
        risk_adjusted_npv = npv * pts

        projects.append({
            "asset_id": asset.id,
            "compound_name": asset.compound_name,
            "therapeutic_area": asset.therapeutic_area,
            "current_phase": asset.current_phase,
            "npv": round(npv, 2),
            "pts": round(pts, 3),
            "risk": round(risk, 3),
            "risk_adjusted_npv": round(risk_adjusted_npv, 2),
            "peak_sales": round(peak_sales, 2),
            "rd_cost": round(rd_cost, 2),
            "quadrant": _get_quadrant(npv, risk),
        })

    efficient = _compute_efficient_frontier(projects)
    for p in projects:
        p["is_efficient"] = p["compound_name"] in efficient

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "projects": projects,
        "efficient_frontier": efficient,
        "total_projects": len(projects),
    }


def _get_quadrant(npv: float, risk: float) -> str:
    if npv >= 0 and risk <= 0.5:
        return "Star (High Return, Low Risk)"
    elif npv >= 0 and risk > 0.5:
        return "Question Mark (High Return, High Risk)"
    elif npv < 0 and risk <= 0.5:
        return "Cash Cow (Low Return, Low Risk)"
    else:
        return "Dog (Low Return, High Risk)"


def _compute_efficient_frontier(projects: list[dict]) -> list[str]:
    """Compute Pareto-optimal set on the risk-return plane."""
    efficient = []
    for p in projects:
        is_dominated = False
        for q in projects:
            if q["compound_name"] == p["compound_name"]:
                continue
            if q["npv"] >= p["npv"] and q["risk"] <= p["risk"]:
                if q["npv"] > p["npv"] or q["risk"] < p["risk"]:
                    is_dominated = True
                    break
        if not is_dominated:
            efficient.append(p["compound_name"])
    return efficient


# ---------------------------------------------------------------------------
# INNOVATION SCORING
# ---------------------------------------------------------------------------

def compute_innovation_score(portfolio_id: int, db: Session) -> dict:
    """Multi-factor innovation score for the portfolio (0-100)."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    phases = set()
    tas = set()
    pts_values = []
    early_stage_count = 0

    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot

        phases.add(asset.current_phase)
        tas.add(asset.therapeutic_area)

        pts = _compute_pts(snapshot)
        if pts > 0:
            pts_values.append(pts)

        if asset.current_phase in ("Phase 1", "Phase 2"):
            early_stage_count += 1

    total_projects = len(portfolio.projects)
    if total_projects == 0:
        return {
            "portfolio_id": portfolio_id,
            "total_score": 0,
            "factors": {},
            "grade": "N/A",
        }

    # Factor 1: Phase diversity (0-25)
    phase_score = min(len(phases) / 4, 1.0) * 25

    # Factor 2: TA diversity (0-25)
    ta_score = min(len(tas) / 3, 1.0) * 25

    # Factor 3: Novelty (0-25)
    if pts_values:
        avg_pts = sum(pts_values) / len(pts_values)
        avg_novelty = 1.0 - avg_pts
        novelty_score = avg_novelty * 25
    else:
        avg_pts = 0
        novelty_score = 0

    # Factor 4: Pipeline depth (0-25)
    early_ratio = early_stage_count / total_projects
    depth_score = min(early_ratio / 0.4, 1.0) * 25

    total_score = phase_score + ta_score + novelty_score + depth_score

    grade = _innovation_grade(total_score)

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_score": round(total_score, 1),
        "max_score": 100,
        "grade": grade,
        "factors": {
            "phase_diversity": {
                "score": round(phase_score, 1),
                "max": 25,
                "detail": f"{len(phases)} unique phases",
                "phases": sorted(phases),
            },
            "ta_diversity": {
                "score": round(ta_score, 1),
                "max": 25,
                "detail": f"{len(tas)} therapeutic areas",
                "areas": sorted(tas),
            },
            "novelty": {
                "score": round(novelty_score, 1),
                "max": 25,
                "detail": (
                    f"Avg novelty: {(1 - avg_pts) * 100:.0f}%"
                    if pts_values else "No PTS data"
                ),
            },
            "pipeline_depth": {
                "score": round(depth_score, 1),
                "max": 25,
                "detail": f"{early_stage_count}/{total_projects} early-stage",
            },
        },
        "total_projects": total_projects,
    }


def _innovation_grade(score: float) -> str:
    if score >= 85:
        return "A (Highly Innovative)"
    if score >= 70:
        return "B (Innovative)"
    if score >= 55:
        return "C (Moderately Innovative)"
    if score >= 40:
        return "D (Conventional)"
    return "F (Low Innovation)"


# ---------------------------------------------------------------------------
# CHARTER COMPLIANCE CHECK
# ---------------------------------------------------------------------------

def check_charter_compliance(
    portfolio_id: int,
    db: Session,
    charter: dict | None = None,
) -> dict:
    """Check portfolio against strategic charter targets."""
    charter = charter or DEFAULT_CHARTER

    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    innovation = compute_innovation_score(portfolio_id, db)

    total_npv = 0
    weighted_pts_sum = 0
    phases = set()
    project_weights = []

    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot

        npv = (snapshot.npv_deterministic or 0) if snapshot else 0
        pts = _compute_pts(snapshot)

        total_npv += npv
        weighted_pts_sum += npv * pts
        phases.add(asset.current_phase)

        project_weights.append({
            "compound_name": asset.compound_name,
            "npv": round(npv, 2),
        })

    portfolio_pts = (
        weighted_pts_sum / total_npv if total_npv > 0 else 0
    ) * 100

    for pw in project_weights:
        pw["weight_pct"] = round(
            (pw["npv"] / abs(total_npv) * 100) if total_npv != 0 else 0, 1
        )

    max_weight = max((pw["weight_pct"] for pw in project_weights), default=0)

    checks = []

    inn_target = charter["min_innovation_score"]
    inn_pass = innovation["total_score"] >= inn_target
    checks.append({
        "criterion": "Innovation Score",
        "target": f">= {inn_target}",
        "actual": round(innovation["total_score"], 1),
        "status": "PASS" if inn_pass else "FAIL",
    })

    pts_target = charter["target_portfolio_pts_pct"]
    pts_pass = portfolio_pts >= pts_target
    checks.append({
        "criterion": "Portfolio PTS",
        "target": f">= {pts_target}%",
        "actual": f"{portfolio_pts:.1f}%",
        "status": "PASS" if pts_pass else "FAIL",
    })

    conc_target = charter["max_single_project_weight_pct"]
    conc_pass = max_weight <= conc_target
    checks.append({
        "criterion": "Max Project Weight",
        "target": f"<= {conc_target}%",
        "actual": f"{max_weight:.1f}%",
        "status": "PASS" if conc_pass else "FAIL",
    })

    div_target = charter["min_phase_diversity"]
    div_pass = len(phases) >= div_target
    checks.append({
        "criterion": "Phase Diversity",
        "target": f">= {div_target} phases",
        "actual": f"{len(phases)} phases",
        "status": "PASS" if div_pass else "FAIL",
    })

    pass_count = sum(1 for c in checks if c["status"] == "PASS")
    overall = "COMPLIANT" if pass_count == len(checks) else "NON-COMPLIANT"

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "charter_targets": charter,
        "overall_status": overall,
        "pass_count": pass_count,
        "total_checks": len(checks),
        "checks": checks,
        "innovation_score": innovation,
        "project_weights": sorted(
            project_weights, key=lambda x: x["weight_pct"], reverse=True
        ),
    }
