"""
PharmaPulse Pydantic Schemas

Defines request/response models for the FastAPI REST API.
Pydantic validates all incoming data and serializes outgoing responses.

Architecture:
    - Create schemas: used for POST request bodies
    - Update schemas: used for PUT request bodies (all fields optional)
    - Response schemas: used for GET/POST response serialization
    - Nested schemas: compose complex responses from simpler pieces

Naming convention:
    - XxxCreate: request body for creating Xxx
    - XxxUpdate: request body for updating Xxx
    - XxxResponse: response body for Xxx
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# ASSET SCHEMAS
# ---------------------------------------------------------------------------

class AssetCreate(BaseModel):
    """Request body for creating a new drug asset."""
    sponsor: str = Field(..., min_length=1, max_length=100)
    compound_name: str = Field(..., min_length=1, max_length=100)
    moa: Optional[str] = None
    therapeutic_area: str = Field(..., min_length=1)
    indication: str = Field(..., min_length=1)
    current_phase: Optional[str] = None
    is_internal: bool
    peak_sales_estimate: Optional[float] = None
    launch_date: Optional[float] = None
    pathway: Optional[str] = None
    biomarker: Optional[str] = None
    innovation_class: str = "standard"
    regulatory_complexity: float = Field(0.5, ge=0.0, le=1.0)

    @field_validator("current_phase")
    @classmethod
    def validate_phase(cls, v):
        valid_phases = [
            "Phase 1", "Phase 2", "Phase 2 B", "Phase 3",
            "Registration", "Approved", None
        ]
        if v not in valid_phases:
            raise ValueError(f"Invalid phase: {v}. Must be one of {valid_phases}")
        return v

    @field_validator("innovation_class")
    @classmethod
    def validate_innovation_class(cls, v):
        valid = ["first_in_class", "best_in_class", "fast_follower", "standard"]
        if v not in valid:
            raise ValueError(f"Invalid innovation_class: {v}. Must be one of {valid}")
        return v


class AssetUpdate(BaseModel):
    """Request body for updating an existing asset. All fields optional."""
    sponsor: Optional[str] = None
    compound_name: Optional[str] = None
    moa: Optional[str] = None
    therapeutic_area: Optional[str] = None
    indication: Optional[str] = None
    current_phase: Optional[str] = None
    is_internal: Optional[bool] = None
    peak_sales_estimate: Optional[float] = None
    launch_date: Optional[float] = None
    pathway: Optional[str] = None
    biomarker: Optional[str] = None
    innovation_class: Optional[str] = None
    regulatory_complexity: Optional[float] = None


class AssetResponse(BaseModel):
    """Response body for a drug asset."""
    id: int
    sponsor: str
    compound_name: str
    moa: Optional[str] = None
    therapeutic_area: str
    indication: str
    current_phase: Optional[str] = None
    is_internal: bool
    peak_sales_estimate: Optional[float] = None
    launch_date: Optional[float] = None
    npv_deterministic: Optional[float] = None
    npv_mc_average: Optional[float] = None
    pathway: Optional[str] = None
    biomarker: Optional[str] = None
    innovation_class: str = "standard"
    regulatory_complexity: float = 0.5
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SNAPSHOT SCHEMAS
# ---------------------------------------------------------------------------

class PhaseInputSchema(BaseModel):
    """Schema for clinical phase inputs."""
    phase_name: str
    start_date: float
    success_rate: float = Field(..., ge=0.0, le=1.0)


class RDCostSchema(BaseModel):
    """Schema for R&D cost entries."""
    year: int
    phase_name: str
    rd_cost: float  # EUR millions (negative = expense)


class CommercialRowSchema(BaseModel):
    """Schema for commercial forecast row."""
    region: str
    scenario: str
    scenario_probability: float = Field(..., ge=0.0, le=1.0)
    segment_name: str
    include_flag: int = 1
    patient_population: float = Field(..., ge=0)
    epi_f1: float = 1.0
    epi_f2: float = 1.0
    epi_f3: float = 1.0
    epi_f4: float = 1.0
    epi_f5: float = 1.0
    epi_f6: float = 1.0
    access_rate: float = Field(..., ge=0.0, le=1.0)
    market_share: float = Field(..., ge=0.0, le=1.0)
    units_per_treatment: float = 1.0
    treatments_per_year: float = 1.0
    compliance_rate: float = 1.0
    gross_price_per_treatment: float = Field(..., ge=0)
    gross_to_net_price_rate: float = Field(1.0, ge=0.0, le=1.0)
    time_to_peak: float = Field(..., gt=0)
    plateau_years: float = Field(..., ge=0)
    revenue_curve_type: str = "logistic"
    cogs_rate: float = Field(..., ge=0.0, le=1.0)
    distribution_rate: float = Field(..., ge=0.0, le=1.0)
    operating_cost_rate: float = Field(..., ge=0.0, le=1.0)
    tax_rate: float = Field(..., ge=0.0, le=1.0)
    wacc_region: float = Field(..., ge=0.0, le=1.0)
    loe_year: float
    launch_date: float
    loe_cliff_rate: float = Field(..., ge=0.0, le=1.0)
    erosion_floor_pct: float = Field(..., ge=0.0, le=1.0)
    years_to_erosion_floor: float = Field(..., ge=0)
    logistic_k: float = 5.5
    logistic_midpoint: float = 0.5


class MCCommercialConfigSchema(BaseModel):
    """Schema for Monte Carlo commercial configuration."""
    use_target_population: str = "Not included"
    use_market_share: str = "Not included"
    use_time_to_peak: str = "Not included"
    use_gross_price: str = "Not included"
    use_price_event: str = "Not included"
    use_market_share_event: str = "Not included"
    # 3-point parameters (all optional)
    low_target_population: Optional[float] = None
    low_target_population_prob: Optional[float] = None
    high_target_population: Optional[float] = None
    high_target_population_prob: Optional[float] = None
    low_market_share: Optional[float] = None
    low_market_share_prob: Optional[float] = None
    high_market_share: Optional[float] = None
    high_market_share_prob: Optional[float] = None
    low_time_to_peak: Optional[float] = None
    low_time_to_peak_prob: Optional[float] = None
    high_time_to_peak: Optional[float] = None
    high_time_to_peak_prob: Optional[float] = None
    low_gross_price: Optional[float] = None
    low_gross_price_prob: Optional[float] = None
    high_gross_price: Optional[float] = None
    high_gross_price_prob: Optional[float] = None
    # Bernoulli event parameters
    price_event_value: Optional[float] = None
    price_event_prob: Optional[float] = None
    market_share_event_value: Optional[float] = None
    market_share_event_prob: Optional[float] = None


class MCRDConfigSchema(BaseModel):
    """Schema for Monte Carlo R&D configuration per phase."""
    phase_name: str
    variable: str  # "Phase Success Rates", "Phase Durations", "R&D Cost multipliers"
    toggle: str = "Not Included"
    min_value: Optional[float] = None
    min_probability: Optional[float] = None
    max_value: Optional[float] = None
    max_probability: Optional[float] = None


class WhatIfPhaseLeverSchema(BaseModel):
    """Schema for what-if phase lever."""
    phase_name: str
    lever_sr: Optional[float] = Field(None, ge=0.0, le=1.0)
    lever_duration_months: float = 0


class SnapshotCreate(BaseModel):
    """Request body for creating a new snapshot with all inputs."""
    snapshot_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    valuation_year: int = Field(..., ge=2020, le=2050)
    horizon_years: int = Field(..., ge=1, le=50)
    wacc_rd: float = Field(..., ge=0.0, le=0.30)
    approval_date: float
    mc_iterations: int = Field(1000, ge=100, le=100000)
    random_seed: int = 42
    whatif_revenue_lever: Optional[float] = None
    whatif_rd_cost_lever: Optional[float] = None
    phase_inputs: list[PhaseInputSchema]
    rd_costs: list[RDCostSchema]
    commercial_rows: list[CommercialRowSchema]
    mc_commercial_config: Optional[MCCommercialConfigSchema] = None
    mc_rd_configs: Optional[list[MCRDConfigSchema]] = None
    whatif_phase_levers: Optional[list[WhatIfPhaseLeverSchema]] = None

    @field_validator("approval_date")
    @classmethod
    def approval_after_valuation(cls, v, info):
        if "valuation_year" in info.data and v < info.data["valuation_year"]:
            # Allow this — means all R&D is sunk
            pass
        return v


class SnapshotResponse(BaseModel):
    """Response body for a snapshot (summary, without all child data)."""
    id: int
    asset_id: int
    snapshot_name: str
    description: Optional[str] = None
    valuation_year: int
    horizon_years: int
    wacc_rd: float
    approval_date: float
    mc_iterations: int
    random_seed: int
    whatif_revenue_lever: Optional[float] = None
    whatif_rd_cost_lever: Optional[float] = None
    npv_deterministic: Optional[float] = None
    npv_deterministic_whatif: Optional[float] = None
    npv_mc_average: Optional[float] = None
    npv_mc_p10: Optional[float] = None
    npv_mc_p25: Optional[float] = None
    npv_mc_p50: Optional[float] = None
    npv_mc_p75: Optional[float] = None
    npv_mc_p90: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SnapshotDetailResponse(BaseModel):
    """Full snapshot detail with all child data."""
    id: int
    asset_id: int
    snapshot_name: str
    description: Optional[str] = None
    valuation_year: int
    horizon_years: int
    wacc_rd: float
    approval_date: float
    mc_iterations: int
    random_seed: int
    whatif_revenue_lever: Optional[float] = None
    whatif_rd_cost_lever: Optional[float] = None
    npv_deterministic: Optional[float] = None
    npv_deterministic_whatif: Optional[float] = None
    npv_mc_average: Optional[float] = None
    npv_mc_p10: Optional[float] = None
    npv_mc_p50: Optional[float] = None
    npv_mc_p90: Optional[float] = None
    created_at: datetime
    phase_inputs: list[PhaseInputSchema]
    rd_costs: list[RDCostSchema]
    commercial_rows: list[CommercialRowSchema]
    mc_commercial_config: Optional[MCCommercialConfigSchema] = None
    mc_rd_configs: Optional[list[MCRDConfigSchema]] = None
    whatif_phase_levers: Optional[list[WhatIfPhaseLeverSchema]] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# PORTFOLIO SCHEMAS
# ---------------------------------------------------------------------------

class PortfolioCreate(BaseModel):
    """Request body for creating a new portfolio."""
    portfolio_name: str = Field(..., min_length=1)
    description: Optional[str] = None
    portfolio_type: str = "base"
    base_portfolio_id: Optional[int] = None
    asset_ids: Optional[list[int]] = None  # v5 — bulk-add at creation

    @field_validator("portfolio_type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("base", "scenario"):
            raise ValueError("portfolio_type must be 'base' or 'scenario'")
        return v


class PortfolioProjectAdd(BaseModel):
    """Request body for adding a project to a portfolio."""
    asset_id: int
    snapshot_id: Optional[int] = None  # If None, uses latest snapshot


class OverrideCreate(BaseModel):
    """Request body for adding a scenario override."""
    portfolio_project_id: int
    override_type: str
    phase_name: Optional[str] = None
    override_value: float
    acceleration_budget_multiplier: Optional[float] = None
    description: Optional[str] = None

    @field_validator("override_type")
    @classmethod
    def validate_override_type(cls, v):
        valid_types = [
            "phase_delay", "peak_sales_change", "sr_override",
            "launch_delay", "time_to_peak_change", "accelerate",
            "budget_realloc", "project_kill", "project_add", "bd_add"
        ]
        if v not in valid_types:
            raise ValueError(f"Invalid override_type: {v}. Must be one of {valid_types}")
        return v


class PortfolioResponse(BaseModel):
    """Response body for a portfolio (list view)."""
    id: int
    portfolio_name: str
    portfolio_type: str
    base_portfolio_id: Optional[int] = None
    total_npv: Optional[float] = None
    created_at: datetime
    project_count: int = 0
    saved_runs_count: int = 0  # v5
    latest_run: Optional[dict] = None  # v5

    model_config = {"from_attributes": True}


class PortfolioProjectResponse(BaseModel):
    """Response for a project within a portfolio."""
    asset_id: int
    compound_name: str
    is_active: bool
    snapshot_id: int
    npv_simulated: Optional[float] = None
    npv_original: Optional[float] = None

    model_config = {"from_attributes": True}


class OverrideResponse(BaseModel):
    """Response for a portfolio override."""
    override_id: int
    project_id: int
    compound_name: str
    override_type: str
    override_value: float
    phase_name: Optional[str] = None
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class PortfolioDetailResponse(BaseModel):
    """Full portfolio detail with projects, overrides, and saved runs."""
    id: int
    portfolio_name: str
    portfolio_type: str
    base_portfolio_id: Optional[int] = None
    total_npv: Optional[float] = None
    total_rd_cost_json: Optional[str] = None
    total_sales_json: Optional[str] = None
    created_at: datetime
    projects: list[PortfolioProjectResponse] = []
    overrides: list[OverrideResponse] = []
    added_projects: list[dict] = []
    bd_placeholders: list[dict] = []
    saved_runs: list[dict] = []  # v5

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# SIMULATION RUN SCHEMAS (v5)
# ---------------------------------------------------------------------------

class SnapshotSettingsUpdate(BaseModel):
    """Request body for updating snapshot MC settings."""
    mc_iterations: Optional[int] = Field(None, ge=100, le=100000)
    random_seed: Optional[int] = None


class SnapshotGeneralUpdate(BaseModel):
    """Request body for updating general snapshot parameters (name, valuation params)."""
    snapshot_name: Optional[str] = None
    description: Optional[str] = None
    valuation_year: Optional[int] = Field(None, ge=2020, le=2050)
    horizon_years: Optional[int] = Field(None, ge=1, le=50)
    wacc_rd: Optional[float] = Field(None, ge=0.0, le=0.30)
    approval_date: Optional[float] = None
    mc_iterations: Optional[int] = Field(None, ge=100, le=100000)
    random_seed: Optional[int] = None


class SimulationRunCreate(BaseModel):
    """Request body for saving a simulation run."""
    run_name: str = Field(..., min_length=1)
    notes: Optional[str] = None


class SimulationRunUpdate(BaseModel):
    """Request body for updating run metadata."""
    run_name: Optional[str] = None
    notes: Optional[str] = None


class SimulationRunResponse(BaseModel):
    """Response body for a saved simulation run."""
    run_id: int
    run_name: str
    total_npv: float
    run_timestamp: datetime
    notes: Optional[str] = None
    overrides_count: int = 0

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# HYPOTHETICAL PROJECT SCHEMAS
# ---------------------------------------------------------------------------

class AddedProjectCreate(BaseModel):
    """Request body for adding a hypothetical project."""
    compound_name: str
    therapeutic_area: Optional[str] = None
    indication: Optional[str] = None
    current_phase: str
    phases_json: str  # JSON string of phase definitions
    rd_costs_json: str  # JSON string of R&D costs
    peak_sales: float = Field(..., gt=0)
    time_to_peak_years: float = Field(..., gt=0)
    approval_date: float
    launch_date: float
    loe_year: float
    wacc_rd: float = 0.08
    wacc_commercial: float = 0.085
    tax_rate: float = 0.21
    cogs_rate: float = 0.04
    operating_cost_rate: float = 0.18
    plateau_years: float = 4.0
    loe_cliff_rate: float = 0.85
    erosion_floor_pct: float = 0.50
    years_to_erosion_floor: float = 4.0


# ---------------------------------------------------------------------------
# BD PLACEHOLDER SCHEMAS
# ---------------------------------------------------------------------------

class BDPlaceholderCreate(BaseModel):
    """Request body for adding a BD placeholder."""
    deal_name: str
    deal_type: str = "in_license"
    therapeutic_area: Optional[str] = None
    indication: Optional[str] = None
    current_phase: str
    upfront_payment: float = 0
    milestone_payments_json: Optional[str] = None
    royalty_rate: float = 0
    peak_sales: float = Field(..., gt=0)
    time_to_peak_years: float = 6
    approval_date: float
    launch_date: float
    loe_year: float
    ptrs_assumed: float = Field(..., gt=0, le=1.0)
    rd_cost_remaining_json: Optional[str] = None
    wacc_rd: float = 0.08
    wacc_commercial: float = 0.085
    tax_rate: float = 0.21
    cogs_rate: float = 0.04
    operating_cost_rate: float = 0.18
    plateau_years: float = 4.0
    loe_cliff_rate: float = 0.85
    erosion_floor_pct: float = 0.50
    years_to_erosion_floor: float = 4.0
    cost_share_pct: float = 1.0
    revenue_share_pct: float = 1.0


# ---------------------------------------------------------------------------
# QUERY / COMPARISON SCHEMAS
# ---------------------------------------------------------------------------

class CashflowResponse(BaseModel):
    """Response body for a cashflow row."""
    cashflow_type: str
    scope: str
    year: int
    revenue: float
    costs: float
    tax: float
    fcf_non_risk_adj: float
    risk_multiplier: float
    fcf_risk_adj: float
    fcf_pv: float

    model_config = {"from_attributes": True}


class NPVResultResponse(BaseModel):
    """Response body for NPV calculation result."""
    npv_deterministic: Optional[float] = None
    npv_deterministic_whatif: Optional[float] = None
    npv_mc_average: Optional[float] = None
    npv_mc_p10: Optional[float] = None
    npv_mc_p25: Optional[float] = None
    npv_mc_p50: Optional[float] = None
    npv_mc_p75: Optional[float] = None
    npv_mc_p90: Optional[float] = None
    peak_sales: Optional[float] = None
    cashflows_count: int = 0

    model_config = {"from_attributes": True}


class ErrorResponse(BaseModel):
    """Standard error response format."""
    detail: str
    error_code: Optional[str] = None
    context: Optional[dict] = None


