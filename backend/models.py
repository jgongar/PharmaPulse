"""SQLAlchemy ORM models for PharmaPulse."""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, Float, Integer, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    therapeutic_area: Mapped[str] = mapped_column(String(100))
    indication: Mapped[str] = mapped_column(String(200))
    molecule_type: Mapped[str] = mapped_column(String(100))
    current_phase: Mapped[str] = mapped_column(String(50))
    is_internal: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="asset", cascade="all, delete-orphan")


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(200), default="Base Case")
    discount_rate: Mapped[float] = mapped_column(Float, default=0.10)
    launch_year: Mapped[int] = mapped_column(Integer, default=2030)
    patent_expiry_year: Mapped[int] = mapped_column(Integer, default=2040)
    peak_sales_usd_m: Mapped[float] = mapped_column(Float, default=500.0)
    time_to_peak_years: Mapped[int] = mapped_column(Integer, default=5)
    generic_erosion_pct: Mapped[float] = mapped_column(Float, default=0.80)
    cogs_pct: Mapped[float] = mapped_column(Float, default=0.20)
    sga_pct: Mapped[float] = mapped_column(Float, default=0.25)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.21)
    uptake_curve: Mapped[str] = mapped_column(String(50), default="linear")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    asset: Mapped["Asset"] = relationship(back_populates="snapshots")
    phase_inputs: Mapped[list["PhaseInput"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    rd_costs: Mapped[list["RDCost"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    commercial_rows: Mapped[list["CommercialRow"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    cashflows: Mapped[list["CashflowRow"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
    mc_config: Mapped[Optional["MCConfig"]] = relationship(back_populates="snapshot", uselist=False, cascade="all, delete-orphan")
    whatif_levers: Mapped[Optional["WhatIfLevers"]] = relationship(back_populates="snapshot", uselist=False, cascade="all, delete-orphan")


class PhaseInput(Base):
    """R&D phase success probabilities and durations."""
    __tablename__ = "phase_inputs"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    phase_name: Mapped[str] = mapped_column(String(50))  # P1, P2, P3, Filing, Approval
    probability_of_success: Mapped[float] = mapped_column(Float)
    duration_years: Mapped[float] = mapped_column(Float)
    start_year: Mapped[int] = mapped_column(Integer)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="phase_inputs")


class RDCost(Base):
    """R&D cost by year."""
    __tablename__ = "rd_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    year: Mapped[int] = mapped_column(Integer)
    cost_usd_m: Mapped[float] = mapped_column(Float)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="rd_costs")


class CommercialRow(Base):
    """Commercial cashflow row (year-by-year projections)."""
    __tablename__ = "commercial_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    year: Mapped[int] = mapped_column(Integer)
    gross_sales_usd_m: Mapped[float] = mapped_column(Float, default=0)
    net_sales_usd_m: Mapped[float] = mapped_column(Float, default=0)
    cogs_usd_m: Mapped[float] = mapped_column(Float, default=0)
    sga_usd_m: Mapped[float] = mapped_column(Float, default=0)
    operating_profit_usd_m: Mapped[float] = mapped_column(Float, default=0)
    tax_usd_m: Mapped[float] = mapped_column(Float, default=0)
    net_cashflow_usd_m: Mapped[float] = mapped_column(Float, default=0)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="commercial_rows")


class CashflowRow(Base):
    """Combined R&D + commercial cashflow row for NPV display."""
    __tablename__ = "cashflow_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    year: Mapped[int] = mapped_column(Integer)
    rd_cost_usd_m: Mapped[float] = mapped_column(Float, default=0)
    commercial_cf_usd_m: Mapped[float] = mapped_column(Float, default=0)
    net_cashflow_usd_m: Mapped[float] = mapped_column(Float, default=0)
    cumulative_pos: Mapped[float] = mapped_column(Float, default=1.0)
    risk_adjusted_cf_usd_m: Mapped[float] = mapped_column(Float, default=0)
    discount_factor: Mapped[float] = mapped_column(Float, default=1.0)
    pv_usd_m: Mapped[float] = mapped_column(Float, default=0)
    cumulative_npv_usd_m: Mapped[float] = mapped_column(Float, default=0)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="cashflows")


class MCConfig(Base):
    """Monte Carlo simulation configuration."""
    __tablename__ = "mc_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"), unique=True)
    n_iterations: Mapped[int] = mapped_column(Integer, default=10000)
    peak_sales_std_pct: Mapped[float] = mapped_column(Float, default=0.20)
    launch_delay_std_years: Mapped[float] = mapped_column(Float, default=1.0)
    pos_variation_pct: Mapped[float] = mapped_column(Float, default=0.10)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="mc_config")


class WhatIfLevers(Base):
    """What-If scenario levers."""
    __tablename__ = "whatif_levers"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"), unique=True)
    peak_sales_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    launch_delay_years: Mapped[int] = mapped_column(Integer, default=0)
    pos_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON dict
    discount_rate_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cogs_pct_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sga_pct_override: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    snapshot: Mapped["Snapshot"] = relationship(back_populates="whatif_levers")


class Portfolio(Base):
    """Named portfolio grouping of assets."""
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members: Mapped[list["PortfolioMember"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class PortfolioMember(Base):
    """Association between portfolio and snapshot."""
    __tablename__ = "portfolio_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))

    portfolio: Mapped["Portfolio"] = relationship(back_populates="members")
