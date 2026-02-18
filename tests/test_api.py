"""Tests for FastAPI endpoints."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database import Base, get_db
from backend.main import app


@pytest.fixture
def client(tmp_path):
    """Create a test client with a file-based temp database."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def asset_id(client):
    """Create a test asset and return its ID."""
    resp = client.post("/api/assets/", json={
        "name": "TestDrug",
        "therapeutic_area": "Oncology",
        "indication": "NSCLC",
        "molecule_type": "Small Molecule",
        "current_phase": "P2",
        "is_internal": True,
    })
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.fixture
def snapshot_id(client, asset_id):
    """Create a test snapshot and return its ID."""
    resp = client.post("/api/snapshots/", json={
        "asset_id": asset_id,
        "label": "Base Case",
        "peak_sales_usd_m": 1000,
        "launch_year": 2030,
        "patent_expiry_year": 2042,
        "discount_rate": 0.10,
        "phase_inputs": [
            {"phase_name": "P2", "probability_of_success": 0.40, "duration_years": 3, "start_year": 2025},
            {"phase_name": "P3", "probability_of_success": 0.55, "duration_years": 3, "start_year": 2028},
            {"phase_name": "Filing", "probability_of_success": 0.90, "duration_years": 1, "start_year": 2031},
            {"phase_name": "Approval", "probability_of_success": 0.95, "duration_years": 1, "start_year": 2032},
        ],
        "rd_costs": [
            {"year": 2025, "cost_usd_m": 16.67},
            {"year": 2026, "cost_usd_m": 16.67},
            {"year": 2027, "cost_usd_m": 16.67},
            {"year": 2028, "cost_usd_m": 50.0},
            {"year": 2029, "cost_usd_m": 50.0},
            {"year": 2030, "cost_usd_m": 50.0},
        ],
    })
    assert resp.status_code == 201
    return resp.json()["id"]


class TestHealthEndpoints:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["app"] == "PharmaPulse v3"

    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAssetEndpoints:
    def test_create_asset(self, client):
        resp = client.post("/api/assets/", json={
            "name": "Drug1", "therapeutic_area": "Oncology",
            "indication": "NSCLC", "current_phase": "P1",
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "Drug1"

    def test_list_assets(self, client, asset_id):
        resp = client.get("/api/assets/")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_asset(self, client, asset_id):
        resp = client.get(f"/api/assets/{asset_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == asset_id

    def test_get_nonexistent_asset(self, client):
        resp = client.get("/api/assets/9999")
        assert resp.status_code == 404

    def test_update_asset(self, client, asset_id):
        resp = client.put(f"/api/assets/{asset_id}", json={"name": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    def test_delete_asset(self, client, asset_id):
        resp = client.delete(f"/api/assets/{asset_id}")
        assert resp.status_code == 200


class TestSnapshotEndpoints:
    def test_create_snapshot(self, client, asset_id):
        resp = client.post("/api/snapshots/", json={
            "asset_id": asset_id, "label": "Test",
        })
        assert resp.status_code == 201
        assert resp.json()["version"] == 1

    def test_list_snapshots(self, client, snapshot_id, asset_id):
        resp = client.get(f"/api/snapshots/asset/{asset_id}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_snapshot(self, client, snapshot_id):
        resp = client.get(f"/api/snapshots/{snapshot_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["phase_inputs"]) == 4
        assert len(data["rd_costs"]) == 6

    def test_update_snapshot(self, client, snapshot_id):
        resp = client.put(f"/api/snapshots/{snapshot_id}", json={
            "label": "Updated Case",
            "peak_sales_usd_m": 2000,
        })
        assert resp.status_code == 200
        assert resp.json()["label"] == "Updated Case"
        assert resp.json()["peak_sales_usd_m"] == 2000

    def test_update_snapshot_phase_inputs(self, client, snapshot_id):
        resp = client.put(f"/api/snapshots/{snapshot_id}", json={
            "phase_inputs": [
                {"phase_name": "P2", "probability_of_success": 0.50,
                 "duration_years": 2, "start_year": 2025},
            ],
        })
        assert resp.status_code == 200
        assert len(resp.json()["phase_inputs"]) == 1
        assert resp.json()["phase_inputs"][0]["probability_of_success"] == 0.50

    def test_delete_snapshot(self, client, snapshot_id):
        resp = client.delete(f"/api/snapshots/{snapshot_id}")
        assert resp.status_code == 200


class TestNPVEndpoints:
    def test_run_deterministic_npv(self, client, snapshot_id):
        resp = client.post(f"/api/npv/deterministic/{snapshot_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "enpv_usd_m" in data
        assert "cumulative_pos" in data
        assert data["enpv_usd_m"] > 0
        assert len(data["cashflows"]) > 0

    def test_npv_nonexistent_snapshot(self, client):
        resp = client.post("/api/npv/deterministic/9999")
        assert resp.status_code == 404


class TestMonteCarloEndpoints:
    def test_run_mc(self, client, snapshot_id):
        # First set MC config with low iterations for speed
        client.put(f"/api/snapshots/{snapshot_id}", json={
            "mc_config": {"n_iterations": 1000, "seed": 42},
        })
        resp = client.post(f"/api/mc/run/{snapshot_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "mean_npv" in data
        assert "median_npv" in data
        assert "prob_positive" in data
        assert data["n_iterations"] == 1000


class TestExportEndpoints:
    def test_excel_export(self, client, snapshot_id):
        # Run NPV first to populate cashflows
        client.post(f"/api/npv/deterministic/{snapshot_id}")
        resp = client.get(f"/api/export/excel/{snapshot_id}")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]


class TestPortfolioEndpoints:
    def test_create_portfolio(self, client, snapshot_id):
        resp = client.post("/api/portfolios/", json={
            "name": "Test Portfolio",
            "snapshot_ids": [snapshot_id],
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Portfolio"

    def test_portfolio_summary(self, client, snapshot_id):
        # Create portfolio
        pf_resp = client.post("/api/portfolios/", json={
            "name": "Summary Test",
            "snapshot_ids": [snapshot_id],
        })
        pf_id = pf_resp.json()["id"]

        resp = client.get(f"/api/portfolios/{pf_id}/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["num_assets"] == 1
        assert data["total_enpv_usd_m"] != 0

    def test_portfolio_cashflows(self, client, snapshot_id):
        # Run NPV first
        client.post(f"/api/npv/deterministic/{snapshot_id}")

        pf_resp = client.post("/api/portfolios/", json={
            "name": "CF Test",
            "snapshot_ids": [snapshot_id],
        })
        pf_id = pf_resp.json()["id"]

        resp = client.get(f"/api/portfolios/{pf_id}/cashflows")
        assert resp.status_code == 200
        assert len(resp.json()) > 0
