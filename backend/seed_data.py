"""
PharmaPulse Database Seed Script

Populates the database with 10 sample drug assets (7 internal + 3 competitors)
and creates "Base Case" snapshots with full valuation inputs for all internal assets.

Architecture:
    - Runs as a standalone script: `python seed_data.py`
    - Creates all tables via init_db()
    - Inserts assets, snapshots, phase_inputs, rd_costs, and commercial_rows
    - Optionally runs deterministic NPV for each internal asset (if engine available)

Usage:
    cd backend
    python seed_data.py

Note: This script is idempotent — running it twice will fail on UNIQUE constraints.
      Delete pharmapulse.db first if you need to re-seed.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path so we can import the backend package
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database import engine, SessionLocal, init_db, Base
from backend.models import (
    Asset, Snapshot, PhaseInput, RDCost, CommercialRow, MCCommercialConfig
)


def seed_database():
    """Main seed function. Creates all assets, snapshots, and inputs."""
    
    # Initialize database (create tables)
    init_db()
    
    db = SessionLocal()
    
    try:
        # Check if already seeded
        existing = db.query(Asset).first()
        if existing:
            print("Database already seeded. Delete pharmapulse.db to re-seed.")
            return
        
        print("Seeding PharmaPulse database with 10 sample assets...")
        
        # ---------------------------------------------------------------
        # ASSET 1: PP-4501 — Atopic Dermatitis (Internal)
        # ---------------------------------------------------------------
        a1 = Asset(
            sponsor="Internal", compound_name="PP-4501",
            moa="Anti-OX40L monoclonal antibody",
            therapeutic_area="Immunology & Inflammation",
            indication="Atopic Dermatitis (moderate-to-severe)",
            current_phase="Phase 3", is_internal=True,
            pathway="OX40L", biomarker=None,
            innovation_class="first_in_class", regulatory_complexity=0.3,
        )
        db.add(a1)
        db.flush()
        
        s1 = Snapshot(
            asset_id=a1.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.072, approval_date=2029.75,
            mc_iterations=1000, random_seed=42,
        )
        db.add(s1)
        db.flush()
        
        # Phase inputs
        for phase_data in [
            ("Phase 1", 2021.0, 1.0), ("Phase 2", 2022.5, 1.0),
            ("Phase 2 B", 2024.0, 1.0), ("Phase 3", 2026.0, 0.65),
            ("Registration", 2028.75, 0.92),
        ]:
            db.add(PhaseInput(
                snapshot_id=s1.id, phase_name=phase_data[0],
                start_date=phase_data[1], success_rate=phase_data[2],
            ))
        
        # R&D costs
        for cost_data in [
            (2026, "Phase 3", -85), (2027, "Phase 3", -120),
            (2028, "Phase 3", -45), (2028, "Registration", -30),
            (2029, "Registration", -55),
        ]:
            db.add(RDCost(
                snapshot_id=s1.id, year=cost_data[0],
                phase_name=cost_data[1], rd_cost=cost_data[2],
            ))
        
        # Commercial: US + EU, Base scenario
        db.add(CommercialRow(
            snapshot_id=s1.id, region="US", scenario="Base",
            scenario_probability=1.0,
            segment_name="Adult AD moderate-severe",
            patient_population=1800000, epi_f1=0.35, epi_f2=0.60,
            access_rate=0.70, market_share=0.12,
            gross_price_per_treatment=35000, gross_to_net_price_rate=0.55,
            time_to_peak=7, plateau_years=4,
            cogs_rate=0.03, distribution_rate=0.02,
            operating_cost_rate=0.15, tax_rate=0.21, wacc_region=0.085,
            loe_year=2042, launch_date=2029.75,
            loe_cliff_rate=0.85, erosion_floor_pct=0.50,
            years_to_erosion_floor=4, logistic_k=5.5, logistic_midpoint=0.5,
        ))
        db.add(CommercialRow(
            snapshot_id=s1.id, region="EU", scenario="Base",
            scenario_probability=1.0,
            segment_name="Adult AD moderate-severe",
            patient_population=2200000, epi_f1=0.30, epi_f2=0.55,
            access_rate=0.60, market_share=0.10,
            gross_price_per_treatment=22000, gross_to_net_price_rate=0.70,
            time_to_peak=8, plateau_years=3,
            cogs_rate=0.03, distribution_rate=0.02,
            operating_cost_rate=0.16, tax_rate=0.27, wacc_region=0.077,
            loe_year=2042, launch_date=2030.25,
            loe_cliff_rate=0.85, erosion_floor_pct=0.50,
            years_to_erosion_floor=4, logistic_k=5.5, logistic_midpoint=0.5,
        ))
        
        print("  [OK] Asset 1: PP-4501 (Atopic Dermatitis)")
        
        # ---------------------------------------------------------------
        # ASSET 2: PP-6120 — Severe Eosinophilic Asthma (Internal)
        # ---------------------------------------------------------------
        a2 = Asset(
            sponsor="Internal", compound_name="PP-6120",
            moa="Anti-TSLP bispecific",
            therapeutic_area="Immunology & Inflammation",
            indication="Severe Eosinophilic Asthma",
            current_phase="Phase 2", is_internal=True,
            pathway="TSLP", biomarker="TSLP",
            innovation_class="best_in_class", regulatory_complexity=0.4,
        )
        db.add(a2)
        db.flush()
        
        s2 = Snapshot(
            asset_id=a2.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.072, approval_date=2032.0,
        )
        db.add(s2)
        db.flush()
        
        for phase_data in [
            ("Phase 1", 2022.0, 1.0), ("Phase 2", 2024.0, 0.35),
            ("Phase 3", 2027.5, 0.60), ("Registration", 2031.0, 0.90),
        ]:
            db.add(PhaseInput(snapshot_id=s2.id, phase_name=phase_data[0],
                              start_date=phase_data[1], success_rate=phase_data[2]))
        
        for cost_data in [
            (2026, "Phase 2", -40), (2027, "Phase 2", -25),
            (2028, "Phase 3", -90), (2029, "Phase 3", -130),
            (2030, "Phase 3", -70), (2031, "Registration", -45),
            (2032, "Registration", -20),
        ]:
            db.add(RDCost(snapshot_id=s2.id, year=cost_data[0],
                          phase_name=cost_data[1], rd_cost=cost_data[2]))
        
        # US Base
        db.add(CommercialRow(
            snapshot_id=s2.id, region="US", scenario="Base",
            scenario_probability=0.7, segment_name="Severe Eosinophilic Asthma",
            patient_population=800000, epi_f1=0.25, epi_f2=0.40,
            access_rate=0.65, market_share=0.08,
            gross_price_per_treatment=28000, gross_to_net_price_rate=0.50,
            time_to_peak=6, plateau_years=5,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.21, wacc_region=0.085,
            loe_year=2044, launch_date=2032.0,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=5,
        ))
        # US Upside
        db.add(CommercialRow(
            snapshot_id=s2.id, region="US", scenario="Upside",
            scenario_probability=0.3, segment_name="Severe Eosinophilic Asthma",
            patient_population=800000, epi_f1=0.25, epi_f2=0.40,
            access_rate=0.65, market_share=0.14,
            gross_price_per_treatment=28000, gross_to_net_price_rate=0.50,
            time_to_peak=6, plateau_years=5,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.21, wacc_region=0.085,
            loe_year=2044, launch_date=2032.0,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=5,
        ))
        # EU Base
        db.add(CommercialRow(
            snapshot_id=s2.id, region="EU", scenario="Base",
            scenario_probability=0.7, segment_name="Severe Eosinophilic Asthma",
            patient_population=1100000, epi_f1=0.25, epi_f2=0.40,
            access_rate=0.55, market_share=0.07,
            gross_price_per_treatment=18000, gross_to_net_price_rate=0.65,
            time_to_peak=7, plateau_years=4,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.27, wacc_region=0.077,
            loe_year=2044, launch_date=2032.5,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=5,
        ))
        # EU Upside
        db.add(CommercialRow(
            snapshot_id=s2.id, region="EU", scenario="Upside",
            scenario_probability=0.3, segment_name="Severe Eosinophilic Asthma",
            patient_population=1100000, epi_f1=0.25, epi_f2=0.40,
            access_rate=0.55, market_share=0.12,
            gross_price_per_treatment=18000, gross_to_net_price_rate=0.65,
            time_to_peak=7, plateau_years=4,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.27, wacc_region=0.077,
            loe_year=2044, launch_date=2032.5,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=5,
        ))
        
        print("  [OK] Asset 2: PP-6120 (Severe Asthma)")
        
        # ---------------------------------------------------------------
        # ASSET 3: PP-2890 — COPD (Internal)
        # ---------------------------------------------------------------
        a3 = Asset(
            sponsor="Internal", compound_name="PP-2890",
            moa="Dual PDE3/4 inhibitor",
            therapeutic_area="Immunology & Inflammation",
            indication="COPD (exacerbation reduction)",
            current_phase="Phase 2 B", is_internal=True,
            pathway="PDE3/PDE4", biomarker=None,
            innovation_class="best_in_class", regulatory_complexity=0.5,
        )
        db.add(a3)
        db.flush()
        
        s3 = Snapshot(
            asset_id=a3.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.072, approval_date=2033.5,
        )
        db.add(s3)
        db.flush()
        
        for phase_data in [
            ("Phase 1", 2021.5, 1.0), ("Phase 2", 2023.0, 1.0),
            ("Phase 2 B", 2025.0, 0.30), ("Phase 3", 2028.0, 0.55),
            ("Registration", 2032.5, 0.88),
        ]:
            db.add(PhaseInput(snapshot_id=s3.id, phase_name=phase_data[0],
                              start_date=phase_data[1], success_rate=phase_data[2]))
        
        for cost_data in [
            (2026, "Phase 2 B", -35), (2027, "Phase 2 B", -20),
            (2028, "Phase 3", -75), (2029, "Phase 3", -110),
            (2030, "Phase 3", -95), (2031, "Phase 3", -40),
            (2032, "Registration", -50), (2033, "Registration", -30),
        ]:
            db.add(RDCost(snapshot_id=s3.id, year=cost_data[0],
                          phase_name=cost_data[1], rd_cost=cost_data[2]))
        
        # US
        db.add(CommercialRow(
            snapshot_id=s3.id, region="US", scenario="Base", scenario_probability=1.0,
            segment_name="COPD exacerbation reduction",
            patient_population=6500000, epi_f1=0.20, epi_f2=0.30,
            access_rate=0.55, market_share=0.05,
            gross_price_per_treatment=15000, gross_to_net_price_rate=0.45,
            time_to_peak=8, plateau_years=4,
            cogs_rate=0.05, distribution_rate=0.03,
            operating_cost_rate=0.20, tax_rate=0.21, wacc_region=0.085,
            loe_year=2046, launch_date=2033.5,
            loe_cliff_rate=0.85, erosion_floor_pct=0.50, years_to_erosion_floor=4,
        ))
        # EU
        db.add(CommercialRow(
            snapshot_id=s3.id, region="EU", scenario="Base", scenario_probability=1.0,
            segment_name="COPD exacerbation reduction",
            patient_population=8000000, epi_f1=0.20, epi_f2=0.30,
            access_rate=0.50, market_share=0.04,
            gross_price_per_treatment=9500, gross_to_net_price_rate=0.60,
            time_to_peak=9, plateau_years=4,
            cogs_rate=0.05, distribution_rate=0.03,
            operating_cost_rate=0.20, tax_rate=0.27, wacc_region=0.077,
            loe_year=2046, launch_date=2034.0,
            loe_cliff_rate=0.85, erosion_floor_pct=0.50, years_to_erosion_floor=4,
        ))
        # ROW
        db.add(CommercialRow(
            snapshot_id=s3.id, region="ROW", scenario="Base", scenario_probability=1.0,
            segment_name="COPD exacerbation reduction",
            patient_population=4000000, epi_f1=0.15, epi_f2=0.25,
            access_rate=0.35, market_share=0.03,
            gross_price_per_treatment=5000, gross_to_net_price_rate=0.50,
            time_to_peak=9, plateau_years=3,
            cogs_rate=0.05, distribution_rate=0.03,
            operating_cost_rate=0.20, tax_rate=0.25, wacc_region=0.09,
            loe_year=2046, launch_date=2034.5,
            loe_cliff_rate=0.85, erosion_floor_pct=0.50, years_to_erosion_floor=4,
        ))
        
        print("  [OK] Asset 3: PP-2890 (COPD)")
        
        # ---------------------------------------------------------------
        # ASSET 4: PP-9210 — NSCLC (Internal)
        # ---------------------------------------------------------------
        a4 = Asset(
            sponsor="Internal", compound_name="PP-9210",
            moa="Bispecific T-cell engager (CD3×DLL3)",
            therapeutic_area="Oncology",
            indication="NSCLC 2L+ (DLL3-expressing)",
            current_phase="Phase 1", is_internal=True,
            pathway="CD3/DLL3", biomarker="DLL3",
            innovation_class="first_in_class", regulatory_complexity=0.7,
        )
        db.add(a4)
        db.flush()
        
        s4 = Snapshot(
            asset_id=a4.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.085, approval_date=2034.0,
        )
        db.add(s4)
        db.flush()
        
        for phase_data in [
            ("Phase 1", 2025.0, 0.55), ("Phase 2", 2027.5, 0.30),
            ("Phase 3", 2030.0, 0.45), ("Registration", 2033.0, 0.85),
        ]:
            db.add(PhaseInput(snapshot_id=s4.id, phase_name=phase_data[0],
                              start_date=phase_data[1], success_rate=phase_data[2]))
        
        for cost_data in [
            (2026, "Phase 1", -15), (2027, "Phase 1", -15),
            (2028, "Phase 2", -50), (2029, "Phase 2", -50),
            (2030, "Phase 3", -100), (2031, "Phase 3", -100),
            (2032, "Phase 3", -80), (2033, "Registration", -35),
        ]:
            db.add(RDCost(snapshot_id=s4.id, year=cost_data[0],
                          phase_name=cost_data[1], rd_cost=cost_data[2]))
        
        # US
        db.add(CommercialRow(
            snapshot_id=s4.id, region="US", scenario="Base", scenario_probability=1.0,
            segment_name="NSCLC 2L+ DLL3+",
            patient_population=120000, epi_f1=0.30, epi_f2=0.50,
            access_rate=0.75, market_share=0.15,
            gross_price_per_treatment=180000, gross_to_net_price_rate=0.55,
            time_to_peak=5, plateau_years=4,
            cogs_rate=0.02, distribution_rate=0.01,
            operating_cost_rate=0.12, tax_rate=0.21, wacc_region=0.085,
            loe_year=2046, launch_date=2034.0,
            loe_cliff_rate=0.70, erosion_floor_pct=0.30, years_to_erosion_floor=3,
        ))
        # EU
        db.add(CommercialRow(
            snapshot_id=s4.id, region="EU", scenario="Base", scenario_probability=1.0,
            segment_name="NSCLC 2L+ DLL3+",
            patient_population=150000, epi_f1=0.30, epi_f2=0.50,
            access_rate=0.60, market_share=0.12,
            gross_price_per_treatment=95000, gross_to_net_price_rate=0.70,
            time_to_peak=6, plateau_years=4,
            cogs_rate=0.02, distribution_rate=0.01,
            operating_cost_rate=0.12, tax_rate=0.27, wacc_region=0.085,
            loe_year=2046, launch_date=2034.5,
            loe_cliff_rate=0.70, erosion_floor_pct=0.30, years_to_erosion_floor=3,
        ))
        
        print("  [OK] Asset 4: PP-9210 (NSCLC)")
        
        # ---------------------------------------------------------------
        # ASSET 5: PP-3340 — Alzheimer's Disease (Internal)
        # ---------------------------------------------------------------
        a5 = Asset(
            sponsor="Internal", compound_name="PP-3340",
            moa="Anti-tau immunotherapy",
            therapeutic_area="Neuroscience",
            indication="Alzheimer's Disease (early-stage)",
            current_phase="Phase 2", is_internal=True,
            pathway="Tau", biomarker="Tau PET",
            innovation_class="first_in_class", regulatory_complexity=0.8,
        )
        db.add(a5)
        db.flush()
        
        s5 = Snapshot(
            asset_id=a5.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.090, approval_date=2034.5,
        )
        db.add(s5)
        db.flush()
        
        for phase_data in [
            ("Phase 1", 2022.0, 1.0), ("Phase 2", 2025.0, 0.15),
            ("Phase 3", 2029.0, 0.40), ("Registration", 2033.5, 0.80),
        ]:
            db.add(PhaseInput(snapshot_id=s5.id, phase_name=phase_data[0],
                              start_date=phase_data[1], success_rate=phase_data[2]))
        
        for cost_data in [
            (2026, "Phase 2", -60), (2027, "Phase 2", -60),
            (2028, "Phase 2", -60),
            (2029, "Phase 3", -250), (2030, "Phase 3", -250),
            (2031, "Phase 3", -250), (2032, "Phase 3", -250),
            (2033, "Registration", -80), (2034, "Registration", -40),
        ]:
            db.add(RDCost(snapshot_id=s5.id, year=cost_data[0],
                          phase_name=cost_data[1], rd_cost=cost_data[2]))
        
        # US Base
        db.add(CommercialRow(
            snapshot_id=s5.id, region="US", scenario="Base", scenario_probability=0.6,
            segment_name="Early-stage Alzheimer's",
            patient_population=6700000, epi_f1=0.15, epi_f2=0.50,
            access_rate=0.50, market_share=0.06,
            gross_price_per_treatment=28000, gross_to_net_price_rate=0.50,
            time_to_peak=8, plateau_years=5,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.21, wacc_region=0.09,
            loe_year=2048, launch_date=2034.5,
            loe_cliff_rate=0.80, erosion_floor_pct=0.40, years_to_erosion_floor=5,
        ))
        # US Downside
        db.add(CommercialRow(
            snapshot_id=s5.id, region="US", scenario="Downside", scenario_probability=0.4,
            segment_name="Early-stage Alzheimer's",
            patient_population=6700000, epi_f1=0.15, epi_f2=0.50,
            access_rate=0.35, market_share=0.03,
            gross_price_per_treatment=28000, gross_to_net_price_rate=0.50,
            time_to_peak=8, plateau_years=4,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.21, wacc_region=0.09,
            loe_year=2048, launch_date=2034.5,
            loe_cliff_rate=0.80, erosion_floor_pct=0.40, years_to_erosion_floor=5,
        ))
        # EU Base
        db.add(CommercialRow(
            snapshot_id=s5.id, region="EU", scenario="Base", scenario_probability=0.6,
            segment_name="Early-stage Alzheimer's",
            patient_population=7500000, epi_f1=0.12, epi_f2=0.45,
            access_rate=0.40, market_share=0.05,
            gross_price_per_treatment=18000, gross_to_net_price_rate=0.65,
            time_to_peak=9, plateau_years=5,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.27, wacc_region=0.085,
            loe_year=2048, launch_date=2035.0,
            loe_cliff_rate=0.80, erosion_floor_pct=0.40, years_to_erosion_floor=5,
        ))
        # EU Downside
        db.add(CommercialRow(
            snapshot_id=s5.id, region="EU", scenario="Downside", scenario_probability=0.4,
            segment_name="Early-stage Alzheimer's",
            patient_population=7500000, epi_f1=0.12, epi_f2=0.45,
            access_rate=0.30, market_share=0.03,
            gross_price_per_treatment=18000, gross_to_net_price_rate=0.65,
            time_to_peak=9, plateau_years=4,
            cogs_rate=0.04, distribution_rate=0.02,
            operating_cost_rate=0.18, tax_rate=0.27, wacc_region=0.085,
            loe_year=2048, launch_date=2035.0,
            loe_cliff_rate=0.80, erosion_floor_pct=0.40, years_to_erosion_floor=5,
        ))
        
        print("  [OK] Asset 5: PP-3340 (Alzheimer's)")
        
        # ---------------------------------------------------------------
        # ASSET 6: PP-7780 — Multiple Sclerosis (Internal)
        # ---------------------------------------------------------------
        a6 = Asset(
            sponsor="Internal", compound_name="PP-7780",
            moa="BTK inhibitor (brain-penetrant)",
            therapeutic_area="Neuroscience",
            indication="Relapsing Multiple Sclerosis",
            current_phase="Phase 3", is_internal=True,
            pathway="BTK", biomarker=None,
            innovation_class="best_in_class", regulatory_complexity=0.5,
        )
        db.add(a6)
        db.flush()
        
        s6 = Snapshot(
            asset_id=a6.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.080, approval_date=2030.0,
        )
        db.add(s6)
        db.flush()
        
        for phase_data in [
            ("Phase 1", 2022.0, 1.0), ("Phase 2", 2023.5, 1.0),
            ("Phase 3", 2025.5, 0.58), ("Registration", 2029.0, 0.90),
        ]:
            db.add(PhaseInput(snapshot_id=s6.id, phase_name=phase_data[0],
                              start_date=phase_data[1], success_rate=phase_data[2]))
        
        for cost_data in [
            (2026, "Phase 3", -65), (2027, "Phase 3", -80),
            (2028, "Phase 3", -40), (2029, "Registration", -35),
        ]:
            db.add(RDCost(snapshot_id=s6.id, year=cost_data[0],
                          phase_name=cost_data[1], rd_cost=cost_data[2]))
        
        # US Base
        db.add(CommercialRow(
            snapshot_id=s6.id, region="US", scenario="Base", scenario_probability=0.7,
            segment_name="Relapsing MS",
            patient_population=450000, epi_f1=0.70, epi_f2=0.80,
            access_rate=0.65, market_share=0.10,
            gross_price_per_treatment=85000, gross_to_net_price_rate=0.50,
            time_to_peak=6, plateau_years=5,
            cogs_rate=0.03, distribution_rate=0.02,
            operating_cost_rate=0.15, tax_rate=0.21, wacc_region=0.085,
            loe_year=2043, launch_date=2030.0,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=4,
        ))
        # US Upside
        db.add(CommercialRow(
            snapshot_id=s6.id, region="US", scenario="Upside", scenario_probability=0.3,
            segment_name="Relapsing MS",
            patient_population=450000, epi_f1=0.70, epi_f2=0.80,
            access_rate=0.65, market_share=0.15,
            gross_price_per_treatment=85000, gross_to_net_price_rate=0.50,
            time_to_peak=6, plateau_years=5,
            cogs_rate=0.03, distribution_rate=0.02,
            operating_cost_rate=0.15, tax_rate=0.21, wacc_region=0.085,
            loe_year=2043, launch_date=2030.0,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=4,
        ))
        # EU Base
        db.add(CommercialRow(
            snapshot_id=s6.id, region="EU", scenario="Base", scenario_probability=0.7,
            segment_name="Relapsing MS",
            patient_population=550000, epi_f1=0.65, epi_f2=0.75,
            access_rate=0.55, market_share=0.08,
            gross_price_per_treatment=45000, gross_to_net_price_rate=0.65,
            time_to_peak=7, plateau_years=5,
            cogs_rate=0.03, distribution_rate=0.02,
            operating_cost_rate=0.15, tax_rate=0.27, wacc_region=0.080,
            loe_year=2043, launch_date=2030.5,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=4,
        ))
        # EU Upside
        db.add(CommercialRow(
            snapshot_id=s6.id, region="EU", scenario="Upside", scenario_probability=0.3,
            segment_name="Relapsing MS",
            patient_population=550000, epi_f1=0.65, epi_f2=0.75,
            access_rate=0.55, market_share=0.12,
            gross_price_per_treatment=45000, gross_to_net_price_rate=0.65,
            time_to_peak=7, plateau_years=5,
            cogs_rate=0.03, distribution_rate=0.02,
            operating_cost_rate=0.15, tax_rate=0.27, wacc_region=0.080,
            loe_year=2043, launch_date=2030.5,
            loe_cliff_rate=0.80, erosion_floor_pct=0.45, years_to_erosion_floor=4,
        ))
        
        print("  [OK] Asset 6: PP-7780 (Multiple Sclerosis)")
        
        # ---------------------------------------------------------------
        # ASSET 7: PP-1155 — AML (Internal)
        # ---------------------------------------------------------------
        a7 = Asset(
            sponsor="Internal", compound_name="PP-1155",
            moa="FLT3/CDK4/6 dual inhibitor",
            therapeutic_area="Hematology",
            indication="Acute Myeloid Leukemia (FLT3-mutated)",
            current_phase="Registration", is_internal=True,
            pathway="FLT3/CDK4/6", biomarker="FLT3",
            innovation_class="first_in_class", regulatory_complexity=0.4,
        )
        db.add(a7)
        db.flush()
        
        s7 = Snapshot(
            asset_id=a7.id, snapshot_name="Base Case",
            valuation_year=2026, horizon_years=28,
            wacc_rd=0.080, approval_date=2027.25,
        )
        db.add(s7)
        db.flush()
        
        for phase_data in [
            ("Phase 1", 2020.0, 1.0), ("Phase 2", 2021.5, 1.0),
            ("Phase 3", 2023.0, 1.0), ("Registration", 2025.5, 0.85),
        ]:
            db.add(PhaseInput(snapshot_id=s7.id, phase_name=phase_data[0],
                              start_date=phase_data[1], success_rate=phase_data[2]))
        
        for cost_data in [
            (2026, "Registration", -25), (2027, "Registration", -10),
        ]:
            db.add(RDCost(snapshot_id=s7.id, year=cost_data[0],
                          phase_name=cost_data[1], rd_cost=cost_data[2]))
        
        # US
        db.add(CommercialRow(
            snapshot_id=s7.id, region="US", scenario="Base", scenario_probability=1.0,
            segment_name="AML FLT3-mutated",
            patient_population=25000, epi_f1=0.30, epi_f2=0.80,
            access_rate=0.80, market_share=0.25,
            gross_price_per_treatment=250000, gross_to_net_price_rate=0.60,
            time_to_peak=4, plateau_years=5,
            cogs_rate=0.02, distribution_rate=0.01,
            operating_cost_rate=0.10, tax_rate=0.21, wacc_region=0.085,
            loe_year=2040, launch_date=2027.25,
            loe_cliff_rate=0.75, erosion_floor_pct=0.35, years_to_erosion_floor=3,
        ))
        # EU
        db.add(CommercialRow(
            snapshot_id=s7.id, region="EU", scenario="Base", scenario_probability=1.0,
            segment_name="AML FLT3-mutated",
            patient_population=30000, epi_f1=0.30, epi_f2=0.80,
            access_rate=0.65, market_share=0.20,
            gross_price_per_treatment=150000, gross_to_net_price_rate=0.70,
            time_to_peak=5, plateau_years=5,
            cogs_rate=0.02, distribution_rate=0.01,
            operating_cost_rate=0.10, tax_rate=0.27, wacc_region=0.080,
            loe_year=2040, launch_date=2027.75,
            loe_cliff_rate=0.75, erosion_floor_pct=0.35, years_to_erosion_floor=3,
        ))
        
        print("  [OK] Asset 7: PP-1155 (AML)")
        
        # ---------------------------------------------------------------
        # ASSET 8: Dupixent — Competitor
        # ---------------------------------------------------------------
        a8 = Asset(
            sponsor="Sanofi/Regeneron", compound_name="Dupixent (dupilumab)",
            moa="Anti-IL-4Rα",
            therapeutic_area="Immunology & Inflammation",
            indication="Atopic Dermatitis",
            current_phase="Approved", is_internal=False,
            peak_sales_estimate=13500, launch_date=2017.25,
            pathway="IL-4/IL-13", innovation_class="first_in_class",
            regulatory_complexity=0.2,
        )
        db.add(a8)
        
        print("  [OK] Asset 8: Dupixent (Competitor)")
        
        # ---------------------------------------------------------------
        # ASSET 9: Tezspire — Competitor
        # ---------------------------------------------------------------
        a9 = Asset(
            sponsor="AstraZeneca/Amgen", compound_name="Tezspire (tezepelumab)",
            moa="Anti-TSLP",
            therapeutic_area="Immunology & Inflammation",
            indication="Severe Asthma",
            current_phase="Approved", is_internal=False,
            peak_sales_estimate=4500, launch_date=2021.83,
            pathway="TSLP", biomarker="TSLP",
            innovation_class="first_in_class", regulatory_complexity=0.3,
        )
        db.add(a9)
        
        print("  [OK] Asset 9: Tezspire (Competitor)")
        
        # ---------------------------------------------------------------
        # ASSET 10: Lecanemab — Competitor
        # ---------------------------------------------------------------
        a10 = Asset(
            sponsor="Eisai/Biogen", compound_name="Lecanemab (leqembi)",
            moa="Anti-amyloid beta",
            therapeutic_area="Neuroscience",
            indication="Alzheimer's Disease (early)",
            current_phase="Approved", is_internal=False,
            peak_sales_estimate=7000, launch_date=2023.0,
            pathway="Amyloid Beta", biomarker="Amyloid PET",
            innovation_class="first_in_class", regulatory_complexity=0.7,
        )
        db.add(a10)
        
        print("  [OK] Asset 10: Lecanemab (Competitor)")
        
        # Commit all
        db.commit()
        
        print(f"\n[SUCCESS] Database seeded successfully!")
        print(f"   - 7 internal assets with Base Case snapshots")
        print(f"   - 3 competitor assets")
        print(f"   - Database: {os.path.abspath('pharmapulse.db')}")
        
        # Optionally run deterministic NPV for internal assets
        try:
            from backend.engines.deterministic import calculate_deterministic_npv
            print("\nRunning deterministic NPV for internal assets...")
            for snapshot in db.query(Snapshot).all():
                result = calculate_deterministic_npv(snapshot.id, db)
                print(f"  [OK] {snapshot.snapshot_name}: NPV = {result.get('npv_deterministic', 'N/A'):.1f} €mm")
        except ImportError:
            print("\n[WARN] NPV engine not yet implemented. Run deterministic NPV later (Phase B).")
        except Exception as e:
            print(f"\n[WARN] NPV calculation failed: {e}")
        
    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()

