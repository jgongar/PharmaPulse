"""Shared test fixtures for PharmaPulse."""

import sys
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.database import Base
from backend import models


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def sample_asset(db_session):
    """Create a sample asset."""
    asset = models.Asset(
        name="TestDrug",
        therapeutic_area="Oncology",
        indication="NSCLC",
        molecule_type="Small Molecule",
        current_phase="P2",
        is_internal=True,
    )
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return asset


@pytest.fixture
def sample_snapshot(db_session, sample_asset):
    """Create a sample snapshot with phase inputs and R&D costs."""
    snap = models.Snapshot(
        asset_id=sample_asset.id,
        version=1,
        label="Base Case",
        discount_rate=0.10,
        launch_year=2030,
        patent_expiry_year=2042,
        peak_sales_usd_m=1000.0,
        time_to_peak_years=5,
        generic_erosion_pct=0.80,
        cogs_pct=0.20,
        sga_pct=0.25,
        tax_rate=0.21,
        uptake_curve="linear",
    )
    db_session.add(snap)
    db_session.flush()

    # Phase inputs
    phases = [
        models.PhaseInput(snapshot_id=snap.id, phase_name="P2", probability_of_success=0.40,
                          duration_years=3, start_year=2025),
        models.PhaseInput(snapshot_id=snap.id, phase_name="P3", probability_of_success=0.55,
                          duration_years=3, start_year=2028),
        models.PhaseInput(snapshot_id=snap.id, phase_name="Filing", probability_of_success=0.90,
                          duration_years=1, start_year=2031),
        models.PhaseInput(snapshot_id=snap.id, phase_name="Approval", probability_of_success=0.95,
                          duration_years=1, start_year=2032),
    ]
    for p in phases:
        db_session.add(p)

    # R&D costs
    rd_costs = [
        models.RDCost(snapshot_id=snap.id, year=2025, cost_usd_m=16.67),
        models.RDCost(snapshot_id=snap.id, year=2026, cost_usd_m=16.67),
        models.RDCost(snapshot_id=snap.id, year=2027, cost_usd_m=16.67),
        models.RDCost(snapshot_id=snap.id, year=2028, cost_usd_m=50.0),
        models.RDCost(snapshot_id=snap.id, year=2029, cost_usd_m=50.0),
        models.RDCost(snapshot_id=snap.id, year=2030, cost_usd_m=50.0),
    ]
    for rc in rd_costs:
        db_session.add(rc)

    db_session.commit()
    db_session.refresh(snap)
    return snap
