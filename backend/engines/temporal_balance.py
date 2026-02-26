"""
PharmaPulse — Family C: Temporal Balance Engine

Analyzes the time-distribution of portfolio cashflows and value:
  - Revenue Gap Analysis:  Identify years with revenue drop-offs (patent cliffs)
  - Launch Timeline:       Map expected launch years per project
  - Temporal Heatmap:      Year x project matrix of contribution to portfolio value
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import Portfolio, Snapshot, Cashflow
from .. import crud


# ---------------------------------------------------------------------------
# LAUNCH TIMELINE
# ---------------------------------------------------------------------------

def get_launch_timeline(portfolio_id: int, db: Session) -> dict:
    """Build a timeline of expected launch years for each project."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    from datetime import date
    current_year = date.today().year

    # Remaining months by phase (approximate)
    phase_remaining = {
        "Phase 1": 60,
        "Phase 2": 48,
        "Phase 2 B": 36,
        "Phase 3": 30,
        "Registration": 12,
        "Approved": 0,
    }

    timeline = []
    for proj in portfolio.projects:
        asset = proj.asset
        snapshot = proj.snapshot
        remaining_months = phase_remaining.get(asset.current_phase, 48)

        # If snapshot has approval_date, use that instead
        if snapshot and snapshot.approval_date:
            est_launch_year = int(snapshot.approval_date)
        else:
            est_launch_year = current_year + (remaining_months // 12)

        timeline.append({
            "asset_id": asset.id,
            "compound_name": asset.compound_name,
            "therapeutic_area": asset.therapeutic_area,
            "current_phase": asset.current_phase,
            "remaining_months": remaining_months,
            "estimated_launch_year": est_launch_year,
            "npv": round(
                (snapshot.npv_deterministic or 0) if snapshot else 0, 2
            ),
        })

    timeline.sort(key=lambda x: x["estimated_launch_year"])

    by_year: dict[int, list] = defaultdict(list)
    for item in timeline:
        by_year[item["estimated_launch_year"]].append(item["compound_name"])

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "projects": timeline,
        "launches_by_year": dict(by_year),
        "total_projects": len(timeline),
    }


# ---------------------------------------------------------------------------
# REVENUE GAP (PATENT CLIFF) ANALYSIS
# ---------------------------------------------------------------------------

def analyze_revenue_gaps(portfolio_id: int, db: Session) -> dict:
    """Identify years where portfolio revenue significantly drops."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    yearly_revenue: dict[int, float] = defaultdict(float)
    yearly_contribution: dict[int, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    for proj in portfolio.projects:
        if not proj.snapshot:
            continue

        # Commercial scopes: US, EU, China, ROW, or any non-R&D scope
        cashflows = (
            db.query(Cashflow)
            .filter(
                Cashflow.snapshot_id == proj.snapshot_id,
                Cashflow.cashflow_type == "deterministic",
                Cashflow.scope != "R&D",
                Cashflow.scope != "Total",
            )
            .all()
        )

        for cf in cashflows:
            rev = cf.revenue or 0.0
            yearly_revenue[cf.year] += rev
            yearly_contribution[cf.year][proj.asset.compound_name] += rev

    if not yearly_revenue:
        return {
            "portfolio_id": portfolio_id,
            "message": "No commercial cashflows found",
            "gaps": [],
            "yearly_data": [],
        }

    years_sorted = sorted(yearly_revenue.keys())

    yearly_data = []
    gaps = []
    prev_rev = 0.0

    for year in years_sorted:
        rev = yearly_revenue[year]
        yoy_change = rev - prev_rev
        yoy_pct = (yoy_change / abs(prev_rev) * 100) if prev_rev != 0 else 0

        entry = {
            "year": year,
            "total_revenue": round(rev, 2),
            "yoy_change": round(yoy_change, 2),
            "yoy_change_pct": round(yoy_pct, 1),
            "contributors": {
                name: round(val, 2)
                for name, val in yearly_contribution[year].items()
            },
        }
        yearly_data.append(entry)

        if yoy_pct < -15 and prev_rev > 0:
            gaps.append({
                "year": year,
                "revenue_drop": round(abs(yoy_change), 2),
                "drop_pct": round(abs(yoy_pct), 1),
                "revenue_before": round(prev_rev, 2),
                "revenue_after": round(rev, 2),
                "severity": (
                    "CRITICAL" if yoy_pct < -30 else
                    "HIGH" if yoy_pct < -20 else
                    "MODERATE"
                ),
            })

        prev_rev = rev

    peak_year_data = max(yearly_data, key=lambda x: x["total_revenue"])

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": portfolio.portfolio_name,
        "yearly_data": yearly_data,
        "gaps": gaps,
        "gap_count": len(gaps),
        "peak_revenue_year": peak_year_data["year"],
        "peak_revenue_eur_mm": peak_year_data["total_revenue"],
        "analysis_range": f"{years_sorted[0]}-{years_sorted[-1]}",
        "recommendation": _gap_recommendation(gaps),
    }


def _gap_recommendation(gaps: list[dict]) -> str:
    if not gaps:
        return "No significant revenue gaps detected. Portfolio temporal balance is good."
    critical = [g for g in gaps if g["severity"] == "CRITICAL"]
    if critical:
        years = ", ".join(str(g["year"]) for g in critical)
        return (
            f"CRITICAL revenue cliffs in year(s): {years}. "
            f"Consider accelerating pipeline projects or BD acquisitions to fill gaps."
        )
    return (
        f"{len(gaps)} revenue gap(s) identified. "
        f"Review launch timing to ensure pipeline coverage."
    )


# ---------------------------------------------------------------------------
# TEMPORAL HEATMAP DATA
# ---------------------------------------------------------------------------

def get_temporal_heatmap(portfolio_id: int, db: Session) -> dict:
    """Generate year x project matrix of NPV contribution for heatmap visualization."""
    portfolio = crud.get_portfolio(db, portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    all_years: set[int] = set()
    project_data: list[dict] = []

    for proj in portfolio.projects:
        if not proj.snapshot:
            continue

        cashflows = (
            db.query(Cashflow)
            .filter(
                Cashflow.snapshot_id == proj.snapshot_id,
                Cashflow.cashflow_type == "deterministic",
                Cashflow.scope == "Total",
            )
            .all()
        )

        year_values: dict[int, float] = {}
        for cf in cashflows:
            net = (cf.revenue or 0) - abs(cf.costs or 0)
            year_values[cf.year] = round(net, 2)
            all_years.add(cf.year)

        project_data.append({
            "asset_id": proj.asset_id,
            "compound_name": proj.asset.compound_name,
            "therapeutic_area": proj.asset.therapeutic_area,
            "values_by_year": year_values,
        })

    years_sorted = sorted(all_years)

    matrix = []
    for proj in project_data:
        row = {
            "compound_name": proj["compound_name"],
            "therapeutic_area": proj["therapeutic_area"],
            "values": [proj["values_by_year"].get(y, 0) for y in years_sorted],
        }
        matrix.append(row)

    return {
        "portfolio_id": portfolio_id,
        "years": years_sorted,
        "projects": [p["compound_name"] for p in project_data],
        "matrix": matrix,
        "project_count": len(project_data),
        "year_count": len(years_sorted),
    }
