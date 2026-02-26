"""
PharmaPulse — Frontend API Client

Centralized HTTP client for all backend API calls.
All frontend components use this module instead of making direct HTTP requests.

Usage:
    from api_client import api
    assets = api.get_assets()
    result = api.run_deterministic_npv(snapshot_id=1)
"""

import requests
from typing import Optional

# Backend URL — configurable via environment
API_BASE = "http://127.0.0.1:8050"


class PharmaPulseAPI:
    """HTTP client wrapper for the PharmaPulse backend API."""

    def __init__(self, base_url: str = API_BASE):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str, params: dict = None) -> dict:
        r = self.session.get(self._url(path), params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json_data: dict = None) -> dict:
        r = self.session.post(self._url(path), json=json_data, timeout=120)
        r.raise_for_status()
        return r.json()

    def _patch(self, path: str, json_data: dict = None) -> dict:
        r = self.session.patch(self._url(path), json=json_data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, json_data: dict = None) -> dict:
        r = self.session.put(self._url(path), json=json_data, timeout=30)
        r.raise_for_status()
        return r.json()

    def _delete(self, path: str) -> dict:
        r = self.session.delete(self._url(path), timeout=30)
        r.raise_for_status()
        return r.json()

    # ---- Health ----
    def health(self) -> dict:
        return self._get("/health")

    # ---- Assets ----
    def get_assets(self, is_internal: bool = None, therapeutic_area: str = None) -> list:
        params = {}
        if is_internal is not None:
            params["is_internal"] = str(is_internal).lower()
        if therapeutic_area:
            params["therapeutic_area"] = therapeutic_area
        return self._get("/api/portfolio", params=params)

    def get_asset(self, asset_id: int) -> dict:
        return self._get(f"/api/portfolio/{asset_id}")

    def create_asset(self, data: dict) -> dict:
        return self._post("/api/portfolio", json_data=data)

    def update_asset(self, asset_id: int, data: dict) -> dict:
        return self._put(f"/api/portfolio/{asset_id}", json_data=data)

    def delete_asset(self, asset_id: int) -> dict:
        return self._delete(f"/api/portfolio/{asset_id}")

    # ---- Snapshots ----
    def get_snapshots(self, asset_id: int) -> list:
        return self._get(f"/api/snapshots/{asset_id}")

    def get_snapshot_detail(self, snapshot_id: int) -> dict:
        return self._get(f"/api/snapshots/detail/{snapshot_id}")

    def create_snapshot(self, asset_id: int, data: dict) -> dict:
        return self._post(f"/api/snapshots/{asset_id}", json_data=data)

    def update_snapshot_settings(self, snapshot_id: int, mc_iterations: int, random_seed: int) -> dict:
        return self._patch(f"/api/snapshots/{snapshot_id}/settings", json_data={
            "mc_iterations": mc_iterations, "random_seed": random_seed,
        })

    def update_mc_commercial_config(self, snapshot_id: int, data: dict) -> dict:
        return self._put(f"/api/snapshots/{snapshot_id}/mc-config", json_data=data)

    def update_mc_rd_configs(self, snapshot_id: int, configs: list) -> dict:
        return self._put(f"/api/snapshots/{snapshot_id}/mc-rd-configs", json_data=configs)

    def clone_snapshot(self, asset_id: int, snapshot_id: int, new_name: str) -> dict:
        return self._post(
            f"/api/snapshots/{asset_id}/{snapshot_id}/clone?new_name={new_name}"
        )

    def update_snapshot_general(self, snapshot_id: int, data: dict) -> dict:
        """Update general snapshot parameters (name, valuation_year, horizon, wacc_rd, etc.)."""
        return self._put(f"/api/snapshots/{snapshot_id}/general", json_data=data)

    def save_whatif_levers(self, snapshot_id: int, data: dict) -> dict:
        """Save what-if lever values (revenue, R&D cost, phase levers) on a snapshot."""
        return self._put(f"/api/snapshots/{snapshot_id}/whatif-levers", json_data=data)

    def add_commercial_row(self, snapshot_id: int, data: dict) -> dict:
        """Add a single commercial row to a snapshot."""
        return self._post(f"/api/snapshots/{snapshot_id}/commercial-rows", json_data=data)

    def replace_commercial_rows(self, snapshot_id: int, rows: list) -> dict:
        """Replace ALL commercial rows for a snapshot."""
        return self._put(f"/api/snapshots/{snapshot_id}/commercial-rows", json_data=rows)

    def delete_commercial_row(self, snapshot_id: int, row_id: int) -> dict:
        """Delete a single commercial row."""
        return self._delete(f"/api/snapshots/{snapshot_id}/commercial-rows/{row_id}")

    # ---- NPV Calculations ----
    def run_deterministic_npv(self, snapshot_id: int) -> dict:
        return self._post(f"/api/npv/deterministic/{snapshot_id}")

    def run_deterministic_whatif(self, snapshot_id: int) -> dict:
        return self._post(f"/api/npv/deterministic-whatif/{snapshot_id}")

    def run_monte_carlo(self, snapshot_id: int) -> dict:
        return self._post(f"/api/npv/montecarlo/{snapshot_id}")

    def get_cashflows(self, snapshot_id: int, cashflow_type: str = "deterministic", scope: str = None) -> dict:
        params = {"cashflow_type": cashflow_type}
        if scope:
            params["scope"] = scope
        return self._get(f"/api/npv/cashflows/{snapshot_id}", params=params)

    # ---- Portfolios ----
    def get_portfolios(self) -> list:
        return self._get("/api/portfolios")

    def create_portfolio(self, data: dict) -> dict:
        return self._post("/api/portfolios", json_data=data)

    def get_portfolio(self, portfolio_id: int) -> dict:
        return self._get(f"/api/portfolios/{portfolio_id}")

    def simulate_portfolio(self, portfolio_id: int) -> dict:
        return self._post(f"/api/portfolios/{portfolio_id}/simulate")

    # ---- Query ----
    def query_assets(self, **params) -> list:
        return self._get("/api/query/assets", params=params)


# Global API client instance
api = PharmaPulseAPI()


