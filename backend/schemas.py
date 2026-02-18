"""Pydantic schemas for PharmaPulse API."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# --- Asset ---
class AssetCreate(BaseModel):
    name: str
    therapeutic_area: str
    indication: str
    molecule_type: str = "Small Molecule"
    current_phase: str = "P1"
    is_internal: bool = True


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    therapeutic_area: Optional[str] = None
    indication: Optional[str] = None
    molecule_type: Optional[str] = None
    current_phase: Optional[str] = None
    is_internal: Optional[bool] = None


class AssetOut(BaseModel):
    id: int
    name: str
    therapeutic_area: str
    indication: str
    molecule_type: str
    current_phase: str
    is_internal: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# --- Phase Input ---
class PhaseInputSchema(BaseModel):
    phase_name: str
    probability_of_success: float
    duration_years: float
    start_year: int


# --- R&D Cost ---
class RDCostSchema(BaseModel):
    year: int
    cost_usd_m: float


# --- Commercial Row ---
class CommercialRowSchema(BaseModel):
    year: int
    gross_sales_usd_m: float = 0
    net_sales_usd_m: float = 0
    cogs_usd_m: float = 0
    sga_usd_m: float = 0
    operating_profit_usd_m: float = 0
    tax_usd_m: float = 0
    net_cashflow_usd_m: float = 0


# --- MC Config ---
class MCConfigSchema(BaseModel):
    n_iterations: int = 10000
    peak_sales_std_pct: float = 0.20
    launch_delay_std_years: float = 1.0
    pos_variation_pct: float = 0.10
    seed: Optional[int] = None


# --- What-If Levers ---
class WhatIfLeversSchema(BaseModel):
    peak_sales_multiplier: float = 1.0
    launch_delay_years: int = 0
    pos_override: Optional[dict] = None
    discount_rate_override: Optional[float] = None
    cogs_pct_override: Optional[float] = None
    sga_pct_override: Optional[float] = None


# --- Snapshot ---
class SnapshotCreate(BaseModel):
    asset_id: int
    label: str = "Base Case"
    discount_rate: float = 0.10
    launch_year: int = 2030
    patent_expiry_year: int = 2040
    peak_sales_usd_m: float = 500.0
    time_to_peak_years: int = 5
    generic_erosion_pct: float = 0.80
    cogs_pct: float = 0.20
    sga_pct: float = 0.25
    tax_rate: float = 0.21
    uptake_curve: str = "linear"
    notes: Optional[str] = None
    phase_inputs: list[PhaseInputSchema] = []
    rd_costs: list[RDCostSchema] = []
    commercial_rows: list[CommercialRowSchema] = []
    mc_config: Optional[MCConfigSchema] = None
    whatif_levers: Optional[WhatIfLeversSchema] = None


class SnapshotUpdate(BaseModel):
    label: Optional[str] = None
    discount_rate: Optional[float] = None
    launch_year: Optional[int] = None
    patent_expiry_year: Optional[int] = None
    peak_sales_usd_m: Optional[float] = None
    time_to_peak_years: Optional[int] = None
    generic_erosion_pct: Optional[float] = None
    cogs_pct: Optional[float] = None
    sga_pct: Optional[float] = None
    tax_rate: Optional[float] = None
    uptake_curve: Optional[str] = None
    notes: Optional[str] = None
    phase_inputs: Optional[list[PhaseInputSchema]] = None
    rd_costs: Optional[list[RDCostSchema]] = None
    commercial_rows: Optional[list[CommercialRowSchema]] = None
    mc_config: Optional[MCConfigSchema] = None
    whatif_levers: Optional[WhatIfLeversSchema] = None


class PhaseInputOut(BaseModel):
    id: int
    phase_name: str
    probability_of_success: float
    duration_years: float
    start_year: int
    model_config = {"from_attributes": True}


class RDCostOut(BaseModel):
    id: int
    year: int
    cost_usd_m: float
    model_config = {"from_attributes": True}


class CommercialRowOut(BaseModel):
    id: int
    year: int
    gross_sales_usd_m: float
    net_sales_usd_m: float
    cogs_usd_m: float
    sga_usd_m: float
    operating_profit_usd_m: float
    tax_usd_m: float
    net_cashflow_usd_m: float
    model_config = {"from_attributes": True}


class CashflowRowOut(BaseModel):
    id: int
    year: int
    rd_cost_usd_m: float
    commercial_cf_usd_m: float
    net_cashflow_usd_m: float
    cumulative_pos: float
    risk_adjusted_cf_usd_m: float
    discount_factor: float
    pv_usd_m: float
    cumulative_npv_usd_m: float
    model_config = {"from_attributes": True}


class MCConfigOut(BaseModel):
    id: int
    n_iterations: int
    peak_sales_std_pct: float
    launch_delay_std_years: float
    pos_variation_pct: float
    seed: Optional[int]
    model_config = {"from_attributes": True}


class WhatIfLeversOut(BaseModel):
    id: int
    peak_sales_multiplier: float
    launch_delay_years: int
    pos_override: Optional[str]
    discount_rate_override: Optional[float]
    cogs_pct_override: Optional[float]
    sga_pct_override: Optional[float]
    model_config = {"from_attributes": True}


class SnapshotOut(BaseModel):
    id: int
    asset_id: int
    version: int
    label: str
    discount_rate: float
    launch_year: int
    patent_expiry_year: int
    peak_sales_usd_m: float
    time_to_peak_years: int
    generic_erosion_pct: float
    cogs_pct: float
    sga_pct: float
    tax_rate: float
    uptake_curve: str
    notes: Optional[str]
    created_at: datetime
    phase_inputs: list[PhaseInputOut] = []
    rd_costs: list[RDCostOut] = []
    commercial_rows: list[CommercialRowOut] = []
    cashflows: list[CashflowRowOut] = []
    mc_config: Optional[MCConfigOut] = None
    whatif_levers: Optional[WhatIfLeversOut] = None
    model_config = {"from_attributes": True}


# --- NPV Results ---
class NPVResult(BaseModel):
    snapshot_id: int
    enpv_usd_m: float
    risk_adjusted_npv_usd_m: float
    unadjusted_npv_usd_m: float
    cumulative_pos: float
    peak_sales_usd_m: float
    launch_year: int
    cashflows: list[CashflowRowOut] = []


# --- MC Results ---
class MCResult(BaseModel):
    snapshot_id: int
    mean_npv: float
    median_npv: float
    std_npv: float
    p5: float
    p25: float
    p75: float
    p95: float
    prob_positive: float
    n_iterations: int
    histogram_data: list[float] = []


# --- Portfolio ---
class PortfolioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    snapshot_ids: list[int] = []


class PortfolioOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    snapshot_ids: list[int] = []
    model_config = {"from_attributes": True}
