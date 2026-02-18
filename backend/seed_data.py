"""Seed the database with 10 sample pharma assets and run NPV for internal ones."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import init_db, SessionLocal
from backend import crud, schemas
from backend.engines.deterministic import run_deterministic_npv

ASSETS = [
    # 7 Internal assets
    {"name": "Nexovir", "therapeutic_area": "Oncology", "indication": "NSCLC",
     "molecule_type": "Small Molecule", "current_phase": "P3", "is_internal": True},
    {"name": "Cardiozen", "therapeutic_area": "Cardiovascular", "indication": "Heart Failure",
     "molecule_type": "Biologic", "current_phase": "P2", "is_internal": True},
    {"name": "Neuralink-7", "therapeutic_area": "Neuroscience", "indication": "Alzheimer's Disease",
     "molecule_type": "Antibody", "current_phase": "P1", "is_internal": True},
    {"name": "Inflammex", "therapeutic_area": "Immunology", "indication": "Rheumatoid Arthritis",
     "molecule_type": "Small Molecule", "current_phase": "P2", "is_internal": True},
    {"name": "Hepacure", "therapeutic_area": "Hepatology", "indication": "NASH",
     "molecule_type": "Small Molecule", "current_phase": "P3", "is_internal": True},
    {"name": "Dermashield", "therapeutic_area": "Dermatology", "indication": "Atopic Dermatitis",
     "molecule_type": "Biologic", "current_phase": "Filing", "is_internal": True},
    {"name": "Pulmofix", "therapeutic_area": "Respiratory", "indication": "Severe Asthma",
     "molecule_type": "Antibody", "current_phase": "P2", "is_internal": True},
    # 3 External/licensed assets
    {"name": "Oncobind (Licensed)", "therapeutic_area": "Oncology", "indication": "Breast Cancer",
     "molecule_type": "ADC", "current_phase": "P1", "is_internal": False},
    {"name": "Retinavue (Licensed)", "therapeutic_area": "Ophthalmology", "indication": "Wet AMD",
     "molecule_type": "Gene Therapy", "current_phase": "P2", "is_internal": False},
    {"name": "Immunovax (Licensed)", "therapeutic_area": "Infectious Disease", "indication": "RSV",
     "molecule_type": "Vaccine", "current_phase": "P3", "is_internal": False},
]

PHASE_TEMPLATES = {
    "P1": [
        {"phase_name": "P1", "probability_of_success": 0.60, "duration_years": 2, "start_year": 2025},
        {"phase_name": "P2", "probability_of_success": 0.40, "duration_years": 3, "start_year": 2027},
        {"phase_name": "P3", "probability_of_success": 0.55, "duration_years": 3, "start_year": 2030},
        {"phase_name": "Filing", "probability_of_success": 0.90, "duration_years": 1, "start_year": 2033},
        {"phase_name": "Approval", "probability_of_success": 0.95, "duration_years": 1, "start_year": 2034},
    ],
    "P2": [
        {"phase_name": "P2", "probability_of_success": 0.40, "duration_years": 3, "start_year": 2025},
        {"phase_name": "P3", "probability_of_success": 0.55, "duration_years": 3, "start_year": 2028},
        {"phase_name": "Filing", "probability_of_success": 0.90, "duration_years": 1, "start_year": 2031},
        {"phase_name": "Approval", "probability_of_success": 0.95, "duration_years": 1, "start_year": 2032},
    ],
    "P3": [
        {"phase_name": "P3", "probability_of_success": 0.55, "duration_years": 3, "start_year": 2025},
        {"phase_name": "Filing", "probability_of_success": 0.90, "duration_years": 1, "start_year": 2028},
        {"phase_name": "Approval", "probability_of_success": 0.95, "duration_years": 1, "start_year": 2029},
    ],
    "Filing": [
        {"phase_name": "Filing", "probability_of_success": 0.90, "duration_years": 1, "start_year": 2025},
        {"phase_name": "Approval", "probability_of_success": 0.95, "duration_years": 1, "start_year": 2026},
    ],
}

SNAPSHOT_PARAMS = {
    "Nexovir": {"peak_sales_usd_m": 2500, "launch_year": 2030, "patent_expiry_year": 2042, "discount_rate": 0.10},
    "Cardiozen": {"peak_sales_usd_m": 1800, "launch_year": 2033, "patent_expiry_year": 2045, "discount_rate": 0.10},
    "Neuralink-7": {"peak_sales_usd_m": 4000, "launch_year": 2035, "patent_expiry_year": 2047, "discount_rate": 0.12},
    "Inflammex": {"peak_sales_usd_m": 1200, "launch_year": 2032, "patent_expiry_year": 2044, "discount_rate": 0.10},
    "Hepacure": {"peak_sales_usd_m": 900, "launch_year": 2030, "patent_expiry_year": 2042, "discount_rate": 0.10},
    "Dermashield": {"peak_sales_usd_m": 1500, "launch_year": 2027, "patent_expiry_year": 2039, "discount_rate": 0.08},
    "Pulmofix": {"peak_sales_usd_m": 800, "launch_year": 2033, "patent_expiry_year": 2045, "discount_rate": 0.10},
    "Oncobind (Licensed)": {"peak_sales_usd_m": 3000, "launch_year": 2035, "patent_expiry_year": 2047, "discount_rate": 0.12},
    "Retinavue (Licensed)": {"peak_sales_usd_m": 600, "launch_year": 2032, "patent_expiry_year": 2044, "discount_rate": 0.10},
    "Immunovax (Licensed)": {"peak_sales_usd_m": 2000, "launch_year": 2029, "patent_expiry_year": 2041, "discount_rate": 0.10},
}


def generate_rd_costs(phases: list[dict]) -> list[dict]:
    """Generate R&D costs based on phases."""
    costs = []
    cost_per_phase = {"P1": 20, "P2": 50, "P3": 150, "Filing": 10, "Approval": 5}
    for phase in phases:
        annual = cost_per_phase.get(phase["phase_name"], 20) / max(phase["duration_years"], 1)
        for y in range(phase["start_year"], phase["start_year"] + int(phase["duration_years"])):
            existing = next((c for c in costs if c["year"] == y), None)
            if existing:
                existing["cost_usd_m"] += annual
            else:
                costs.append({"year": y, "cost_usd_m": round(annual, 2)})
    return sorted(costs, key=lambda x: x["year"])


def seed():
    init_db()
    db = SessionLocal()

    # Check if already seeded
    if crud.get_assets(db):
        print("Database already seeded. Skipping.")
        db.close()
        return

    print("Seeding database with 10 assets...")

    for asset_data in ASSETS:
        asset = crud.create_asset(db, schemas.AssetCreate(**asset_data))
        print(f"  Created asset: {asset.name} (ID={asset.id})")

        phase = asset_data["current_phase"]
        phases = PHASE_TEMPLATES.get(phase, PHASE_TEMPLATES["P2"])
        params = SNAPSHOT_PARAMS.get(asset.name, {})
        rd_costs = generate_rd_costs(phases)

        snap_data = schemas.SnapshotCreate(
            asset_id=asset.id,
            label="Base Case",
            phase_inputs=[schemas.PhaseInputSchema(**p) for p in phases],
            rd_costs=[schemas.RDCostSchema(**c) for c in rd_costs],
            **params,
        )
        snap = crud.create_snapshot(db, snap_data)
        print(f"    Snapshot v{snap.version} created (ID={snap.id})")

        # Run deterministic NPV for internal assets
        if asset.is_internal:
            snap_loaded = crud.get_snapshot(db, snap.id)
            result = run_deterministic_npv(db, snap_loaded)
            print(f"    eNPV: ${result['enpv_usd_m']:.1f}M  |  cPOS: {result['cumulative_pos']:.2%}")

    db.close()
    print("\nSeeding complete!")


if __name__ == "__main__":
    seed()
