"""
PharmaPulse ORM Models

Defines all database tables using SQLAlchemy 2.0 mapped_column style.
These models map directly to the database schema described in the specification.

Architecture:
    - All models inherit from Base (defined in database.py)
    - Relationships defined with back_populates for bidirectional access
    - CASCADE deletes configured so removing a parent cleans up children
    - UNIQUE constraints enforce business rules (e.g., no duplicate assets)

Tables:
    - assets: Master table for all drug assets (internal + competitor)
    - snapshots: Named valuation snapshots per asset
    - phase_inputs: Clinical phase timeline & success rates per snapshot
    - rd_costs: R&D expenditure by year/phase per snapshot
    - commercial_rows: Commercial forecast by region×scenario×segment per snapshot
    - mc_commercial_config: Monte Carlo toggles for commercial variables
    - mc_rd_config: Monte Carlo toggles for R&D variables per phase
    - whatif_phase_levers: What-If levers per phase per snapshot
    - cashflows: Calculated cashflows by year per snapshot (output)
    - portfolios: Portfolio containers (base or scenario)
    - portfolio_projects: Links assets to portfolios
    - portfolio_scenario_overrides: What-if overrides for scenario portfolios
    - portfolio_results: Ephemeral simulation results per project
    - portfolio_added_projects: Hypothetical projects not in assets table
    - portfolio_bd_placeholders: BD deal placeholder assets
    - portfolio_simulation_runs: Frozen snapshots of portfolio simulations (v5)
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer, Float, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, String
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---------------------------------------------------------------------------
# ASSET TABLES
# ---------------------------------------------------------------------------

class Asset(Base):
    """
    Master table for all assets in the portfolio (internal + competitors).
    
    Internal assets have full valuation data (snapshots, phases, costs, etc.).
    Competitor assets only have this master record (for landscape context).
    
    Simulation family columns (pathway, biomarker, innovation_class, 
    regulatory_complexity) support advanced strategy analysis.
    """
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("sponsor", "compound_name", "indication", name="uq_asset_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sponsor: Mapped[str] = mapped_column(Text, nullable=False)
    compound_name: Mapped[str] = mapped_column(Text, nullable=False)
    moa: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    therapeutic_area: Mapped[str] = mapped_column(Text, nullable=False)
    indication: Mapped[str] = mapped_column(Text, nullable=False)
    current_phase: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    peak_sales_estimate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    launch_date: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_deterministic: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_average: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Simulation family columns
    pathway: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    biomarker: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    innovation_class: Mapped[str] = mapped_column(
        Text, nullable=False, default="standard"
    )
    regulatory_complexity: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    snapshots: Mapped[list["Snapshot"]] = relationship(
        "Snapshot", back_populates="asset", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Asset(id={self.id}, compound={self.compound_name}, TA={self.therapeutic_area})>"


class Snapshot(Base):
    """
    Named valuation snapshot for an asset. Captures a complete set of
    inputs + results at a point in time. Each snapshot is independent —
    modifying one does not affect others.
    """
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("asset_id", "snapshot_name", name="uq_snapshot_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Valuation parameters
    valuation_year: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False)
    wacc_rd: Mapped[float] = mapped_column(Float, nullable=False)
    approval_date: Mapped[float] = mapped_column(Float, nullable=False)
    mc_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False, default=42)

    # What-If levers (asset-level)
    whatif_revenue_lever: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    whatif_rd_cost_lever: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Results (populated after calculation)
    npv_deterministic: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_deterministic_whatif: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_average: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_p10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_p25: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_p50: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_p75: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_mc_p90: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mc_distribution_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # Relationships
    asset: Mapped["Asset"] = relationship("Asset", back_populates="snapshots")
    phase_inputs: Mapped[list["PhaseInput"]] = relationship(
        "PhaseInput", back_populates="snapshot", cascade="all, delete-orphan"
    )
    rd_costs: Mapped[list["RDCost"]] = relationship(
        "RDCost", back_populates="snapshot", cascade="all, delete-orphan"
    )
    commercial_rows: Mapped[list["CommercialRow"]] = relationship(
        "CommercialRow", back_populates="snapshot", cascade="all, delete-orphan"
    )
    mc_commercial_config: Mapped[Optional["MCCommercialConfig"]] = relationship(
        "MCCommercialConfig", back_populates="snapshot", uselist=False,
        cascade="all, delete-orphan"
    )
    mc_rd_configs: Mapped[list["MCRDConfig"]] = relationship(
        "MCRDConfig", back_populates="snapshot", cascade="all, delete-orphan"
    )
    whatif_phase_levers: Mapped[list["WhatIfPhaseLever"]] = relationship(
        "WhatIfPhaseLever", back_populates="snapshot", cascade="all, delete-orphan"
    )
    cashflows: Mapped[list["Cashflow"]] = relationship(
        "Cashflow", back_populates="snapshot", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Snapshot(id={self.id}, name='{self.snapshot_name}', asset_id={self.asset_id})>"


class PhaseInput(Base):
    """
    Clinical development phase timeline and success rates for a snapshot.
    Phases are in fixed order: Phase 1 → Phase 2 → Phase 2 B → Phase 3 → Registration.
    """
    __tablename__ = "phase_inputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    phase_name: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[float] = mapped_column(Float, nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="phase_inputs")

    def __repr__(self) -> str:
        return f"<PhaseInput(id={self.id}, phase='{self.phase_name}', SR={self.success_rate})>"


class RDCost(Base):
    """
    R&D expenditure by year and phase for a snapshot.
    Costs are in EUR millions (negative = expense).
    """
    __tablename__ = "rd_costs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_name: Mapped[str] = mapped_column(Text, nullable=False)
    rd_cost: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="rd_costs")

    def __repr__(self) -> str:
        return f"<RDCost(year={self.year}, phase='{self.phase_name}', cost={self.rd_cost})>"


class CommercialRow(Base):
    """
    Commercial forecast data by region × scenario × segment.
    Contains all parameters needed for revenue/cost/NPV calculation.
    
    Key fields:
    - patient_population: absolute number of people (NOT millions)
    - gross_price_per_treatment: in EUR (NOT millions)
    - Revenue is computed as patient_pop × filters × price → converted to millions
    - epi_f1 through epi_f6: epidemiological adjustment factors
    """
    __tablename__ = "commercial_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    region: Mapped[str] = mapped_column(Text, nullable=False)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_probability: Mapped[float] = mapped_column(Float, nullable=False)
    segment_name: Mapped[str] = mapped_column(Text, nullable=False)
    include_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Population & epidemiology
    patient_population: Mapped[float] = mapped_column(Float, nullable=False)
    epi_f1: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    epi_f2: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    epi_f3: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    epi_f4: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    epi_f5: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    epi_f6: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Market access & pricing
    access_rate: Mapped[float] = mapped_column(Float, nullable=False)
    market_share: Mapped[float] = mapped_column(Float, nullable=False)
    units_per_treatment: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    treatments_per_year: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    compliance_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    gross_price_per_treatment: Mapped[float] = mapped_column(Float, nullable=False)
    gross_to_net_price_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # Revenue curve parameters
    time_to_peak: Mapped[float] = mapped_column(Float, nullable=False)
    plateau_years: Mapped[float] = mapped_column(Float, nullable=False)
    revenue_curve_type: Mapped[str] = mapped_column(Text, nullable=False, default="logistic")

    # Cost & discount rates
    cogs_rate: Mapped[float] = mapped_column(Float, nullable=False)
    distribution_rate: Mapped[float] = mapped_column(Float, nullable=False)
    operating_cost_rate: Mapped[float] = mapped_column(Float, nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False)
    wacc_region: Mapped[float] = mapped_column(Float, nullable=False)

    # LOE & launch
    loe_year: Mapped[float] = mapped_column(Float, nullable=False)
    launch_date: Mapped[float] = mapped_column(Float, nullable=False)
    loe_cliff_rate: Mapped[float] = mapped_column(Float, nullable=False)
    erosion_floor_pct: Mapped[float] = mapped_column(Float, nullable=False)
    years_to_erosion_floor: Mapped[float] = mapped_column(Float, nullable=False)

    # Logistic curve parameters
    logistic_k: Mapped[float] = mapped_column(Float, nullable=True, default=5.5)
    logistic_midpoint: Mapped[float] = mapped_column(Float, nullable=True, default=0.5)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="commercial_rows")

    def __repr__(self) -> str:
        return (
            f"<CommercialRow(region='{self.region}', scenario='{self.scenario}', "
            f"segment='{self.segment_name}')>"
        )


class MCCommercialConfig(Base):
    """
    Monte Carlo toggle settings and parameters for commercial variables.
    One row per snapshot (1:1 relationship).
    
    Toggle values:
    - "Not included": variable is deterministic
    - "Independent": new draw per region-scenario per iteration
    - "Same for all regions and scenarios": one draw applied everywhere
    - "Same for all scenarios within the same region": one draw per region
    - "Same for all regions within the same scenario": one draw per scenario
    """
    __tablename__ = "mc_commercial_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Toggles
    use_target_population: Mapped[str] = mapped_column(Text, nullable=False, default="Not included")
    use_market_share: Mapped[str] = mapped_column(Text, nullable=False, default="Not included")
    use_time_to_peak: Mapped[str] = mapped_column(Text, nullable=False, default="Not included")
    use_gross_price: Mapped[str] = mapped_column(Text, nullable=False, default="Not included")
    use_price_event: Mapped[str] = mapped_column(Text, nullable=False, default="Not included")
    use_market_share_event: Mapped[str] = mapped_column(Text, nullable=False, default="Not included")

    # 3-point variable parameters for target_population
    low_target_population: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_target_population_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_target_population: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_target_population_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 3-point variable parameters for market_share
    low_market_share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_market_share_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_market_share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_market_share_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 3-point variable parameters for time_to_peak
    low_time_to_peak: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_time_to_peak_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_time_to_peak: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_time_to_peak_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 3-point variable parameters for gross_price
    low_gross_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_gross_price_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_gross_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_gross_price_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Bernoulli event parameters
    price_event_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_event_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_share_event_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_share_event_prob: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="mc_commercial_config")

    def __repr__(self) -> str:
        return f"<MCCommercialConfig(snapshot_id={self.snapshot_id})>"


class MCRDConfig(Base):
    """
    Monte Carlo toggle settings and parameters for R&D variables, per phase.
    Variables: Phase Success Rates, Phase Durations, R&D Cost multipliers.
    """
    __tablename__ = "mc_rd_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    phase_name: Mapped[str] = mapped_column(Text, nullable=False)
    variable: Mapped[str] = mapped_column(Text, nullable=False)
    toggle: Mapped[str] = mapped_column(Text, nullable=False, default="Not Included")
    min_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="mc_rd_configs")

    def __repr__(self) -> str:
        return f"<MCRDConfig(phase='{self.phase_name}', var='{self.variable}', toggle='{self.toggle}')>"


class WhatIfPhaseLever(Base):
    """
    What-If levers applied per phase for a snapshot.
    - lever_sr: absolute success rate override (NULL = no change)
    - lever_duration_months: months to add (positive=delay, negative=accelerate)
    """
    __tablename__ = "whatif_phase_levers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    phase_name: Mapped[str] = mapped_column(Text, nullable=False)
    lever_sr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lever_duration_months: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="whatif_phase_levers")

    def __repr__(self) -> str:
        return f"<WhatIfPhaseLever(phase='{self.phase_name}', sr={self.lever_sr}, months={self.lever_duration_months})>"


class Cashflow(Base):
    """
    Stores calculated cashflows by year for a snapshot (output of NPV calculation).
    One row per (snapshot_id, cashflow_type, scope, year) combination.
    
    cashflow_type: "deterministic" or "deterministic_whatif"
    scope: "R&D", "US", "EU", "China", "ROW", or "Total"
    """
    __tablename__ = "cashflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    cashflow_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    costs: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    fcf_non_risk_adj: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    risk_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    fcf_risk_adj: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    fcf_pv: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # Relationship
    snapshot: Mapped["Snapshot"] = relationship("Snapshot", back_populates="cashflows")

    def __repr__(self) -> str:
        return f"<Cashflow(type='{self.cashflow_type}', scope='{self.scope}', year={self.year})>"


# ---------------------------------------------------------------------------
# PORTFOLIO TABLES
# ---------------------------------------------------------------------------

class Portfolio(Base):
    """
    Portfolio container. Can be 'base' (original set of projects) or
    'scenario' (derived from a base with overrides applied).
    
    Scenario portfolios reference their base_portfolio_id.
    Totals are populated after running portfolio simulation.
    """
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    portfolio_type: Mapped[str] = mapped_column(Text, nullable=False, default="base")
    base_portfolio_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True
    )
    total_npv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_rd_cost_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_sales_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    projects: Mapped[list["PortfolioProject"]] = relationship(
        "PortfolioProject", back_populates="portfolio", cascade="all, delete-orphan"
    )
    results: Mapped[list["PortfolioResult"]] = relationship(
        "PortfolioResult", back_populates="portfolio", cascade="all, delete-orphan"
    )
    added_projects: Mapped[list["PortfolioAddedProject"]] = relationship(
        "PortfolioAddedProject", back_populates="portfolio", cascade="all, delete-orphan"
    )
    bd_placeholders: Mapped[list["PortfolioBDPlaceholder"]] = relationship(
        "PortfolioBDPlaceholder", back_populates="portfolio", cascade="all, delete-orphan"
    )
    simulation_runs: Mapped[list["PortfolioSimulationRun"]] = relationship(
        "PortfolioSimulationRun", back_populates="portfolio", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Portfolio(id={self.id}, name='{self.portfolio_name}', type='{self.portfolio_type}')>"


class PortfolioProject(Base):
    """
    Links an asset (via its snapshot) to a portfolio.
    is_active=False means the project has been cancelled/killed in a scenario.
    """
    __tablename__ = "portfolio_projects"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "asset_id", name="uq_portfolio_asset"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="projects")
    asset: Mapped["Asset"] = relationship("Asset")
    snapshot: Mapped["Snapshot"] = relationship("Snapshot")
    overrides: Mapped[list["PortfolioScenarioOverride"]] = relationship(
        "PortfolioScenarioOverride", back_populates="portfolio_project",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<PortfolioProject(portfolio_id={self.portfolio_id}, "
            f"asset_id={self.asset_id}, active={self.is_active})>"
        )


class PortfolioScenarioOverride(Base):
    """
    What-if overrides for scenario portfolios. Each override modifies
    one aspect of a project's valuation within the portfolio context.
    
    Override types — parameter modifications:
        phase_delay, peak_sales_change, sr_override, launch_delay,
        time_to_peak_change, accelerate, budget_realloc
    
    Override types — structural changes (v5):
        project_kill, project_add, bd_add
    
    This table is the SINGLE SOURCE OF TRUTH for all scenario changes.
    """
    __tablename__ = "portfolio_scenario_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_project_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("portfolio_projects.id", ondelete="CASCADE"), nullable=True
    )
    reference_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    override_type: Mapped[str] = mapped_column(Text, nullable=False)
    phase_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_value: Mapped[float] = mapped_column(Float, nullable=False)
    acceleration_budget_multiplier: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    acceleration_timeline_reduction: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    portfolio_project: Mapped[Optional["PortfolioProject"]] = relationship(
        "PortfolioProject", back_populates="overrides"
    )

    def __repr__(self) -> str:
        return (
            f"<Override(type='{self.override_type}', value={self.override_value}, "
            f"project_id={self.portfolio_project_id})>"
        )


class PortfolioResult(Base):
    """
    Ephemeral simulation results per project in a portfolio.
    Recalculated every simulation run — not persisted across runs.
    To preserve results for comparison, use PortfolioSimulationRun (v5).
    """
    __tablename__ = "portfolio_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    compound_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    npv_original: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_simulated: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    npv_used: Mapped[float] = mapped_column(Float, nullable=False)
    rd_cost_by_year_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sales_by_year_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overrides_applied_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="results")

    def __repr__(self) -> str:
        return f"<PortfolioResult(portfolio_id={self.portfolio_id}, asset='{self.compound_name}')>"


class PortfolioAddedProject(Base):
    """
    Hypothetical new projects that don't exist in the assets table.
    Simplified model: single region, single scenario, peak_sales provided directly.
    """
    __tablename__ = "portfolio_added_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    compound_name: Mapped[str] = mapped_column(Text, nullable=False)
    therapeutic_area: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indication: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_phase: Mapped[str] = mapped_column(Text, nullable=False)
    phases_json: Mapped[str] = mapped_column(Text, nullable=False)
    rd_costs_json: Mapped[str] = mapped_column(Text, nullable=False)
    peak_sales: Mapped[float] = mapped_column(Float, nullable=False)
    time_to_peak_years: Mapped[float] = mapped_column(Float, nullable=False)
    approval_date: Mapped[float] = mapped_column(Float, nullable=False)
    launch_date: Mapped[float] = mapped_column(Float, nullable=False)
    loe_year: Mapped[float] = mapped_column(Float, nullable=False)
    wacc_rd: Mapped[float] = mapped_column(Float, nullable=False, default=0.08)
    wacc_commercial: Mapped[float] = mapped_column(Float, nullable=False, default=0.085)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.21)
    cogs_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.04)
    operating_cost_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.18)
    plateau_years: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    loe_cliff_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    erosion_floor_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    years_to_erosion_floor: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    npv_calculated: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rd_cost_by_year_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sales_by_year_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="added_projects")

    def __repr__(self) -> str:
        return f"<PortfolioAddedProject(id={self.id}, name='{self.compound_name}')>"


class PortfolioBDPlaceholder(Base):
    """
    Business Development placeholder assets for Simulation Family E.
    Represents in-licensing, co-development, or option deals.
    """
    __tablename__ = "portfolio_bd_placeholders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    deal_name: Mapped[str] = mapped_column(Text, nullable=False)
    deal_type: Mapped[str] = mapped_column(Text, nullable=False, default="in_license")
    therapeutic_area: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indication: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_phase: Mapped[str] = mapped_column(Text, nullable=False)
    upfront_payment: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    milestone_payments_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    royalty_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    peak_sales: Mapped[float] = mapped_column(Float, nullable=False)
    time_to_peak_years: Mapped[float] = mapped_column(Float, nullable=False, default=6)
    approval_date: Mapped[float] = mapped_column(Float, nullable=False)
    launch_date: Mapped[float] = mapped_column(Float, nullable=False)
    loe_year: Mapped[float] = mapped_column(Float, nullable=False)
    ptrs_assumed: Mapped[float] = mapped_column(Float, nullable=False)
    rd_cost_remaining_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wacc_rd: Mapped[float] = mapped_column(Float, nullable=False, default=0.08)
    wacc_commercial: Mapped[float] = mapped_column(Float, nullable=False, default=0.085)
    tax_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.21)
    cogs_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.04)
    operating_cost_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.18)
    plateau_years: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    loe_cliff_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    erosion_floor_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.50)
    years_to_erosion_floor: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    cost_share_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    revenue_share_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    npv_calculated: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_deal_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rd_cost_by_year_json_out: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sales_by_year_json_out: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="bd_placeholders")

    def __repr__(self) -> str:
        return f"<BDPlaceholder(id={self.id}, deal='{self.deal_name}', type='{self.deal_type}')>"


class PortfolioSimulationRun(Base):
    """
    Frozen snapshot of a portfolio simulation (v5 — NEW).
    
    Analogous to how asset-level snapshots capture point-in-time valuations,
    this table captures a point-in-time portfolio simulation state with all
    overrides, results, and metrics frozen for audit trail and comparison.
    
    Lifecycle:
    1. User/LLM runs portfolio simulation → results in portfolio_results (mutable)
    2. User/LLM says "Save" → frozen copy written here (immutable)
    3. Saved runs are never overwritten; new saves create new rows
    4. Comparing any two saved runs is supported
    5. Restoring a run reloads its overrides into the mutable state
    """
    __tablename__ = "portfolio_simulation_runs"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "run_name", name="uq_portfolio_run_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False
    )
    run_name: Mapped[str] = mapped_column(Text, nullable=False)
    run_timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    total_npv: Mapped[float] = mapped_column(Float, nullable=False)
    total_rd_cost_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_sales_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    overrides_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    results_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    added_projects_snapshot_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bd_placeholders_snapshot_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deactivated_assets_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    simulation_families_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    portfolio: Mapped["Portfolio"] = relationship("Portfolio", back_populates="simulation_runs")

    def __repr__(self) -> str:
        return f"<SimulationRun(id={self.id}, name='{self.run_name}', npv={self.total_npv})>"


