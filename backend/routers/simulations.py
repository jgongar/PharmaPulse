"""
Simulation Families Router — /api/simulations

Provides API endpoints for all 6 strategic simulation families:
    A. Kill / Continue / Accelerate
    B. TA Budget Reallocation
    C. Temporal Balance
    D. Innovation vs Risk Charter
    E. BD Cut & Reinvest
    F. Concentration Risk

Each family has multiple endpoints for different analyses.
All engines are in backend/engines/.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db

router = APIRouter(prefix="/api/simulations", tags=["Simulation Families"])


# =========================================================================
# REQUEST MODELS
# =========================================================================

class AccelerationRequest(BaseModel):
    budget_multiplier: float = Field(
        1.5, ge=1.0, le=2.0,
        description="Budget multiplier (1.0 = no change, 2.0 = double budget)"
    )
    phase_name: Optional[str] = Field(
        None, description="Phase to accelerate (default: current phase)"
    )

class KillAndReinvestRequest(BaseModel):
    kill_asset_id: int = Field(..., description="Asset ID to kill")
    accelerate_asset_id: int = Field(..., description="Asset ID to accelerate")
    accelerate_phase_name: Optional[str] = None

class BudgetShiftRequest(BaseModel):
    source_ta: str = Field(..., description="Therapeutic area to reduce")
    target_ta: str = Field(..., description="Therapeutic area to increase")
    shift_amount_eur_mm: float = Field(..., gt=0, description="Amount to shift")

class BDDealRequest(BaseModel):
    peak_sales_eur_mm: float = Field(..., gt=0)
    market_share_pct: float = Field(..., gt=0, le=100)
    margin_pct: float = Field(70.0, gt=0, le=100)
    years_to_launch: int = Field(..., ge=1)
    commercial_duration_years: int = Field(10, ge=1)
    upfront_eur_mm: float = Field(..., ge=0)
    milestones_eur_mm: float = Field(0.0, ge=0)
    royalty_pct: float = Field(0.0, ge=0, le=50)
    wacc: float = Field(0.10, gt=0, lt=1)
    pts: float = Field(0.5, gt=0, le=1)

class BDCutReinvestRequest(BaseModel):
    cut_asset_id: int = Field(..., description="Asset to cut from portfolio")
    deal: BDDealRequest

class CharterTargets(BaseModel):
    min_innovation_score: float = Field(60, ge=0, le=100)
    target_portfolio_pts_pct: float = Field(40, ge=0, le=100)
    max_single_project_weight_pct: float = Field(30, ge=0, le=100)
    min_phase_diversity: int = Field(3, ge=1, le=6)


# =========================================================================
# FAMILY A — Kill / Continue / Accelerate
# =========================================================================

@router.get("/family-a/kill/{portfolio_id}/{asset_id}")
def kill_analysis(
    portfolio_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
):
    """
    Analyze the financial impact of killing a project.
    Returns NPV lost, budget freed, and portfolio impact.
    """
    try:
        from ..engines.acceleration import analyze_kill_impact
        return analyze_kill_impact(portfolio_id, asset_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/family-a/accelerate/{portfolio_id}/{asset_id}")
def acceleration_analysis(
    portfolio_id: int,
    asset_id: int,
    req: AccelerationRequest,
    db: Session = Depends(get_db),
):
    """
    Analyze the impact of accelerating a project's timeline by increasing budget.
    Returns months saved, cost, NPV gain, and acceleration curve data.
    """
    try:
        from ..engines.acceleration import analyze_acceleration
        return analyze_acceleration(
            portfolio_id, asset_id,
            req.budget_multiplier, db, req.phase_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-a/acceleration-curve")
def get_acceleration_curve(
    duration_months: float = Query(24, description="Original phase duration"),
    cost_eur_mm: float = Query(50, description="Original phase cost"),
):
    """
    Generate pure acceleration curve data for visualization.
    No portfolio context needed.
    """
    from ..engines.acceleration import generate_acceleration_curve_data
    return {
        "original_duration_months": duration_months,
        "original_cost_eur_mm": cost_eur_mm,
        "curve": generate_acceleration_curve_data(duration_months, cost_eur_mm),
    }


@router.post("/family-a/kill-and-reinvest/{portfolio_id}")
def kill_and_reinvest_analysis(
    portfolio_id: int,
    req: KillAndReinvestRequest,
    db: Session = Depends(get_db),
):
    """
    Combined analysis: kill one project and reinvest freed budget to accelerate another.
    """
    try:
        from ..engines.acceleration import analyze_kill_and_reinvest
        return analyze_kill_and_reinvest(
            portfolio_id,
            req.kill_asset_id,
            req.accelerate_asset_id,
            db,
            req.accelerate_phase_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FAMILY B — TA Budget Reallocation
# =========================================================================

@router.get("/family-b/ta-summary/{portfolio_id}")
def ta_summary(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Aggregate portfolio data by therapeutic area.
    Returns NPV, cost, efficiency, and project counts per TA.
    """
    try:
        from ..engines.ta_reallocation import get_ta_summary
        return get_ta_summary(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/family-b/budget-shift/{portfolio_id}")
def budget_shift_analysis(
    portfolio_id: int,
    req: BudgetShiftRequest,
    db: Session = Depends(get_db),
):
    """
    Analyze the NPV impact of shifting R&D budget from one TA to another.
    """
    try:
        from ..engines.ta_reallocation import analyze_budget_shift
        return analyze_budget_shift(
            portfolio_id, req.source_ta, req.target_ta,
            req.shift_amount_eur_mm, db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-b/ta-efficiency/{portfolio_id}")
def ta_efficiency_ranking(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Rank therapeutic areas by NPV efficiency and suggest optimal budget allocation.
    """
    try:
        from ..engines.ta_reallocation import rank_ta_efficiency
        return rank_ta_efficiency(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FAMILY C — Temporal Balance
# =========================================================================

@router.get("/family-c/launch-timeline/{portfolio_id}")
def launch_timeline(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Get the launch timeline for all projects in the portfolio.
    Maps estimated launch years based on current development phase.
    """
    try:
        from ..engines.temporal_balance import get_launch_timeline
        return get_launch_timeline(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-c/revenue-gaps/{portfolio_id}")
def revenue_gap_analysis(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Analyze year-over-year revenue changes to identify patent cliffs and gaps.
    Flags years with >15% revenue drops.
    """
    try:
        from ..engines.temporal_balance import analyze_revenue_gaps
        return analyze_revenue_gaps(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-c/temporal-heatmap/{portfolio_id}")
def temporal_heatmap(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Generate year x project NPV contribution heatmap data.
    """
    try:
        from ..engines.temporal_balance import get_temporal_heatmap
        return get_temporal_heatmap(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FAMILY D — Innovation vs Risk Charter
# =========================================================================

@router.get("/family-d/risk-return/{portfolio_id}")
def risk_return_scatter(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Generate risk-return scatter data for all projects.
    X=Risk (1-PTS), Y=NPV, with quadrant classification and efficient frontier.
    """
    try:
        from ..engines.innovation_risk import get_risk_return_scatter
        return get_risk_return_scatter(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-d/innovation-score/{portfolio_id}")
def innovation_score(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Compute multi-factor innovation score (0-100) for the portfolio.
    Evaluates phase diversity, TA diversity, novelty, and pipeline depth.
    """
    try:
        from ..engines.innovation_risk import compute_innovation_score
        return compute_innovation_score(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/family-d/charter-compliance/{portfolio_id}")
def charter_compliance(
    portfolio_id: int,
    charter: Optional[CharterTargets] = None,
    db: Session = Depends(get_db),
):
    """
    Check portfolio compliance against strategic innovation/risk charter targets.
    Pass custom charter targets or use defaults.
    """
    try:
        from ..engines.innovation_risk import check_charter_compliance
        charter_dict = charter.model_dump() if charter else None
        return check_charter_compliance(portfolio_id, db, charter_dict)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FAMILY E — BD Cut & Reinvest
# =========================================================================

@router.post("/family-e/value-deal")
def value_bd_deal_endpoint(
    deal: BDDealRequest,
):
    """
    Value a BD deal (in-licensing or acquisition).
    No portfolio context needed — pure financial valuation.
    """
    try:
        from ..engines.bd_modeling import value_bd_deal
        return value_bd_deal(**deal.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/family-e/cut-reinvest/{portfolio_id}")
def bd_cut_reinvest(
    portfolio_id: int,
    req: BDCutReinvestRequest,
    db: Session = Depends(get_db),
):
    """
    Analyze cutting an existing project and replacing with a BD deal.
    Side-by-side comparison of current project vs BD acquisition.
    """
    try:
        from ..engines.bd_modeling import analyze_bd_cut_reinvest
        return analyze_bd_cut_reinvest(
            portfolio_id, req.cut_asset_id,
            req.deal.model_dump(), db,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-e/bd-scan/{portfolio_id}")
def bd_opportunity_scan(
    portfolio_id: int,
    min_npv: float = Query(0, description="Flag projects below this NPV"),
    max_pts: float = Query(0.3, description="Flag projects below this PTS"),
    db: Session = Depends(get_db),
):
    """
    Scan portfolio for projects that could be candidates for BD replacement.
    """
    try:
        from ..engines.bd_modeling import scan_bd_opportunities
        return scan_bd_opportunities(portfolio_id, db, min_npv, max_pts)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# FAMILY F — Concentration Risk
# =========================================================================

@router.get("/family-f/hhi/{portfolio_id}")
def hhi_analysis(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Compute Herfindahl-Hirschman Index (HHI) across project, TA, and phase dimensions.
    """
    try:
        from ..engines.concentration import compute_hhi
        return compute_hhi(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-f/top-n/{portfolio_id}")
def top_n_dependency(
    portfolio_id: int,
    n_values: str = Query("1,2,3,5", description="Comma-separated N values"),
    db: Session = Depends(get_db),
):
    """
    Analyze what percentage of portfolio NPV depends on the top-N projects.
    """
    try:
        from ..engines.concentration import analyze_top_n_dependency
        n_list = [int(x.strip()) for x in n_values.split(",")]
        return analyze_top_n_dependency(portfolio_id, db, n_list)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-f/diversification/{portfolio_id}")
def diversification_score(
    portfolio_id: int,
    db: Session = Depends(get_db),
):
    """
    Compute multi-factor diversification score (0-100) for the portfolio.
    """
    try:
        from ..engines.concentration import compute_diversification_score
        return compute_diversification_score(portfolio_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/family-f/stress-test/{portfolio_id}")
def stress_test(
    portfolio_id: int,
    n_failures: int = Query(3, ge=1, le=10, description="Number of failures to test"),
    db: Session = Depends(get_db),
):
    """
    Simulate the impact of top-N projects failing simultaneously.
    """
    try:
        from ..engines.concentration import stress_test_failures
        return stress_test_failures(portfolio_id, db, n_failures)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# OVERVIEW — List all families & endpoints
# =========================================================================

@router.get("/families")
def list_simulation_families():
    """
    List all available simulation families and their endpoints.
    """
    return {
        "families": [
            {
                "id": "A",
                "name": "Kill / Continue / Accelerate",
                "description": "Project go/no-go and acceleration decisions",
                "endpoints": [
                    "GET  /api/simulations/family-a/kill/{portfolio_id}/{asset_id}",
                    "POST /api/simulations/family-a/accelerate/{portfolio_id}/{asset_id}",
                    "GET  /api/simulations/family-a/acceleration-curve",
                    "POST /api/simulations/family-a/kill-and-reinvest/{portfolio_id}",
                ],
            },
            {
                "id": "B",
                "name": "TA Budget Reallocation",
                "description": "Therapeutic area budget shifts and efficiency ranking",
                "endpoints": [
                    "GET  /api/simulations/family-b/ta-summary/{portfolio_id}",
                    "POST /api/simulations/family-b/budget-shift/{portfolio_id}",
                    "GET  /api/simulations/family-b/ta-efficiency/{portfolio_id}",
                ],
            },
            {
                "id": "C",
                "name": "Temporal Balance",
                "description": "Launch timeline, revenue gaps, and temporal heatmap",
                "endpoints": [
                    "GET /api/simulations/family-c/launch-timeline/{portfolio_id}",
                    "GET /api/simulations/family-c/revenue-gaps/{portfolio_id}",
                    "GET /api/simulations/family-c/temporal-heatmap/{portfolio_id}",
                ],
            },
            {
                "id": "D",
                "name": "Innovation vs Risk Charter",
                "description": "Risk-return scatter, innovation scoring, charter compliance",
                "endpoints": [
                    "GET  /api/simulations/family-d/risk-return/{portfolio_id}",
                    "GET  /api/simulations/family-d/innovation-score/{portfolio_id}",
                    "POST /api/simulations/family-d/charter-compliance/{portfolio_id}",
                ],
            },
            {
                "id": "E",
                "name": "BD Cut & Reinvest",
                "description": "BD deal valuation, cut-and-replace analysis, portfolio scan",
                "endpoints": [
                    "POST /api/simulations/family-e/value-deal",
                    "POST /api/simulations/family-e/cut-reinvest/{portfolio_id}",
                    "GET  /api/simulations/family-e/bd-scan/{portfolio_id}",
                ],
            },
            {
                "id": "F",
                "name": "Concentration Risk",
                "description": "HHI analysis, top-N dependency, diversification score, stress test",
                "endpoints": [
                    "GET /api/simulations/family-f/hhi/{portfolio_id}",
                    "GET /api/simulations/family-f/top-n/{portfolio_id}",
                    "GET /api/simulations/family-f/diversification/{portfolio_id}",
                    "GET /api/simulations/family-f/stress-test/{portfolio_id}",
                ],
            },
        ],
        "total_endpoints": 17,
    }


