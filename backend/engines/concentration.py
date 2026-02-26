"""
PharmaPulse — Family F: Concentration Risk Engine

Analyzes portfolio concentration risk across multiple dimensions:
  - HHI (Herfindahl-Hirschman Index):  Measure concentration by NPV, TA, phase
  - Top-N Dependency:                    What % of value from top N projects
  - Diversification Score:               Multi-factor diversification rating
  - Stress Test:                         Impact if top-1/2/3 projects fail

HHI interpretation:
    < 1500  = Low concentration (well diversified)
    1500-2500 = Moderate concentration
    > 2500  = High concentration (risky)
"""

from sqlalchemy.orm import Session
from collections import defaultdict

from ..models import Portfolio
from .. import crud


# ---------------------------------------------------------------------------
# HHI CALCULATION
# ---------------------------------------------------------------------------

def compute_hhi(portfolio_id: int, db: Session) -> dict:
    """Compute HHI across project, TA, and phase dimensions."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    project_npvs: list[dict] = []
    ta_npvs: dict[str, float] = defaultdict(float)
    phase_npvs: dict[str, float] = defaultdict(float)
    total_npv = 0.0

    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot
        npv = abs((snapshot.npv_deterministic or 0) if snapshot else 0)

        project_npvs.append({
            "compound_name": asset.compound_name,
            "npv": npv,
        })
        ta_npvs[asset.therapeutic_area or "Unknown"] += npv
        phase_npvs[asset.current_phase or "Unknown"] += npv
        total_npv += npv

    if total_npv == 0:
        return {
            "portfolio_id": portfolio_id,
            "message": "No NPV data - cannot compute HHI",
            "hhi_by_project": 0,
            "hhi_by_ta": 0,
            "hhi_by_phase": 0,
        }

    hhi_project = sum(
        ((p["npv"] / total_npv) * 100) ** 2 for p in project_npvs
    )
    project_shares = [
        {
            "name": p["compound_name"],
            "npv": round(p["npv"], 2),
            "share_pct": round(p["npv"] / total_npv * 100, 1),
        }
        for p in sorted(project_npvs, key=lambda x: x["npv"], reverse=True)
    ]

    hhi_ta = sum(
        ((v / total_npv) * 100) ** 2 for v in ta_npvs.values()
    )
    ta_shares = [
        {
            "name": ta,
            "npv": round(npv, 2),
            "share_pct": round(npv / total_npv * 100, 1),
        }
        for ta, npv in sorted(ta_npvs.items(), key=lambda x: x[1], reverse=True)
    ]

    hhi_phase = sum(
        ((v / total_npv) * 100) ** 2 for v in phase_npvs.values()
    )
    phase_shares = [
        {
            "name": ph,
            "npv": round(npv, 2),
            "share_pct": round(npv / total_npv * 100, 1),
        }
        for ph, npv in sorted(phase_npvs.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_npv": round(total_npv, 2),
        "hhi_by_project": {
            "hhi": round(hhi_project, 0),
            "interpretation": _interpret_hhi(hhi_project),
            "shares": project_shares,
        },
        "hhi_by_ta": {
            "hhi": round(hhi_ta, 0),
            "interpretation": _interpret_hhi(hhi_ta),
            "shares": ta_shares,
        },
        "hhi_by_phase": {
            "hhi": round(hhi_phase, 0),
            "interpretation": _interpret_hhi(hhi_phase),
            "shares": phase_shares,
        },
    }


def _interpret_hhi(hhi: float) -> str:
    if hhi < 1500:
        return "LOW concentration (well diversified)"
    if hhi < 2500:
        return "MODERATE concentration"
    return "HIGH concentration (risk)"


# ---------------------------------------------------------------------------
# TOP-N DEPENDENCY
# ---------------------------------------------------------------------------

def analyze_top_n_dependency(
    portfolio_id: int,
    db: Session,
    n_values: list[int] | None = None,
) -> dict:
    """Calculate what percentage of portfolio NPV depends on top N projects."""
    if n_values is None:
        n_values = [1, 2, 3, 5]

    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    projects = []
    total_npv = 0.0

    for proj in portfolio.projects:
        npv = (proj.snapshot.npv_deterministic or 0) if proj.snapshot else 0
        projects.append({
            "compound_name": proj.asset.compound_name,
            "therapeutic_area": proj.asset.therapeutic_area,
            "npv": npv,
        })
        total_npv += npv

    projects.sort(key=lambda x: x["npv"], reverse=True)

    top_n_results = []
    for n in n_values:
        actual_n = min(n, len(projects))
        top_projects = projects[:actual_n]
        top_npv = sum(p["npv"] for p in top_projects)
        top_share = (top_npv / abs(total_npv) * 100) if total_npv != 0 else 0

        top_n_results.append({
            "n": n,
            "top_npv": round(top_npv, 2),
            "share_pct": round(top_share, 1),
            "projects": [
                {
                    "compound_name": p["compound_name"],
                    "npv": round(p["npv"], 2),
                }
                for p in top_projects
            ],
            "risk_level": (
                "HIGH" if top_share > 60 else
                "MODERATE" if top_share > 40 else
                "LOW"
            ),
        })

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_npv": round(total_npv, 2),
        "total_projects": len(projects),
        "top_n_analysis": top_n_results,
        "all_projects_ranked": [
            {
                "rank": i + 1,
                "compound_name": p["compound_name"],
                "npv": round(p["npv"], 2),
                "cumulative_share_pct": round(
                    sum(pp["npv"] for pp in projects[:i+1]) / abs(total_npv) * 100
                    if total_npv != 0 else 0, 1
                ),
            }
            for i, p in enumerate(projects)
        ],
    }


# ---------------------------------------------------------------------------
# DIVERSIFICATION SCORE
# ---------------------------------------------------------------------------

def compute_diversification_score(portfolio_id: int, db: Session) -> dict:
    """Multi-factor diversification score (0-100)."""
    hhi_data = compute_hhi(portfolio_id, db)

    if isinstance(hhi_data.get("hhi_by_project"), dict):
        hhi_project = hhi_data["hhi_by_project"]["hhi"]
        hhi_ta = hhi_data["hhi_by_ta"]["hhi"]
        hhi_phase = hhi_data["hhi_by_phase"]["hhi"]
    else:
        return {
            "portfolio_id": portfolio_id,
            "total_score": 0,
            "grade": "N/A",
            "message": hhi_data.get("message", "Insufficient data"),
        }

    portfolio = crud.get_portfolio(db, portfolio_id)
    n_projects = len(portfolio.projects)

    count_score = min(n_projects / 10, 1.0) * 25
    ta_score = max(0, (1 - hhi_ta / 10000)) * 25
    phase_score = max(0, (1 - hhi_phase / 10000)) * 25
    npv_score = max(0, (1 - hhi_project / 10000)) * 25

    total = count_score + ta_score + phase_score + npv_score

    grade = _diversification_grade(total)

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_score": round(total, 1),
        "max_score": 100,
        "grade": grade,
        "factors": {
            "project_count": {
                "score": round(count_score, 1),
                "max": 25,
                "detail": f"{n_projects} projects",
            },
            "ta_spread": {
                "score": round(ta_score, 1),
                "max": 25,
                "detail": f"TA HHI: {hhi_ta:.0f}",
            },
            "phase_balance": {
                "score": round(phase_score, 1),
                "max": 25,
                "detail": f"Phase HHI: {hhi_phase:.0f}",
            },
            "npv_balance": {
                "score": round(npv_score, 1),
                "max": 25,
                "detail": f"Project HHI: {hhi_project:.0f}",
            },
        },
        "hhi_details": hhi_data,
    }


def _diversification_grade(score: float) -> str:
    if score >= 80:
        return "A (Well Diversified)"
    if score >= 60:
        return "B (Adequately Diversified)"
    if score >= 40:
        return "C (Moderately Concentrated)"
    if score >= 20:
        return "D (Concentrated)"
    return "F (Highly Concentrated)"


# ---------------------------------------------------------------------------
# STRESS TEST — TOP PROJECT FAILURES
# ---------------------------------------------------------------------------

def stress_test_failures(
    portfolio_id: int,
    db: Session,
    n_failures: int = 3,
) -> dict:
    """Simulate the impact of the top-N projects failing simultaneously."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    projects = []
    total_npv = 0.0
    for proj in portfolio.projects:
        npv = (proj.snapshot.npv_deterministic or 0) if proj.snapshot else 0
        projects.append({
            "compound_name": proj.asset.compound_name,
            "therapeutic_area": proj.asset.therapeutic_area,
            "current_phase": proj.asset.current_phase,
            "npv": npv,
        })
        total_npv += npv

    projects.sort(key=lambda x: x["npv"], reverse=True)

    scenarios = []
    for n in range(1, min(n_failures + 1, len(projects) + 1)):
        failed = projects[:n]
        surviving = projects[n:]

        lost_npv = sum(p["npv"] for p in failed)
        remaining_npv = total_npv - lost_npv
        loss_pct = (lost_npv / abs(total_npv) * 100) if total_npv != 0 else 0

        scenarios.append({
            "scenario": f"Top-{n} fail",
            "failed_projects": [
                {
                    "compound_name": p["compound_name"],
                    "npv": round(p["npv"], 2),
                }
                for p in failed
            ],
            "npv_lost": round(lost_npv, 2),
            "loss_pct": round(loss_pct, 1),
            "remaining_npv": round(remaining_npv, 2),
            "surviving_count": len(surviving),
            "severity": (
                "CRITICAL" if loss_pct > 50 else
                "HIGH" if loss_pct > 30 else
                "MODERATE" if loss_pct > 15 else
                "LOW"
            ),
        })

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "total_npv": round(total_npv, 2),
        "total_projects": len(projects),
        "n_failures_tested": min(n_failures, len(projects)),
        "scenarios": scenarios,
        "recommendation": _stress_recommendation(scenarios),
    }


def _stress_recommendation(scenarios: list[dict]) -> str:
    critical = [s for s in scenarios if s["severity"] == "CRITICAL"]
    if critical and critical[0]["scenario"] == "Top-1 fail":
        return (
            "CRITICAL: Losing the single largest project would devastate the portfolio "
            f"(-{critical[0]['loss_pct']:.0f}%). Urgent need to diversify or de-risk."
        )
    if critical:
        return (
            f"Portfolio shows critical vulnerability if top projects fail. "
            f"Consider strengthening pipeline depth and diversification."
        )
    return (
        "Portfolio shows reasonable resilience to top-project failures. "
        "Continue monitoring concentration risk."
    )
