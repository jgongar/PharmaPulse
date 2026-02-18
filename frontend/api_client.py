"""API client for communicating with PharmaPulse backend."""

import requests
from typing import Optional

BASE_URL = "http://localhost:8000"


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def _handle(resp: requests.Response):
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"API error {resp.status_code}: {detail}")
    return resp.json()


# --- Assets ---
def list_assets() -> list[dict]:
    return _handle(requests.get(_url("/api/assets/")))


def get_asset(asset_id: int) -> dict:
    return _handle(requests.get(_url(f"/api/assets/{asset_id}")))


def create_asset(data: dict) -> dict:
    return _handle(requests.post(_url("/api/assets/"), json=data))


def update_asset(asset_id: int, data: dict) -> dict:
    return _handle(requests.put(_url(f"/api/assets/{asset_id}"), json=data))


def delete_asset(asset_id: int):
    return _handle(requests.delete(_url(f"/api/assets/{asset_id}")))


# --- Snapshots ---
def list_snapshots(asset_id: int) -> list[dict]:
    return _handle(requests.get(_url(f"/api/snapshots/asset/{asset_id}")))


def get_snapshot(snapshot_id: int) -> dict:
    return _handle(requests.get(_url(f"/api/snapshots/{snapshot_id}")))


def create_snapshot(data: dict) -> dict:
    return _handle(requests.post(_url("/api/snapshots/"), json=data))


def update_snapshot(snapshot_id: int, data: dict) -> dict:
    return _handle(requests.put(_url(f"/api/snapshots/{snapshot_id}"), json=data))


def delete_snapshot(snapshot_id: int):
    return _handle(requests.delete(_url(f"/api/snapshots/{snapshot_id}")))


# --- NPV ---
def run_deterministic_npv(snapshot_id: int) -> dict:
    return _handle(requests.post(_url(f"/api/npv/deterministic/{snapshot_id}")))


# --- Monte Carlo ---
def run_monte_carlo(snapshot_id: int) -> dict:
    return _handle(requests.post(_url(f"/api/mc/run/{snapshot_id}")))


# --- Export ---
def get_export_url(snapshot_id: int) -> str:
    return _url(f"/api/export/excel/{snapshot_id}")


# --- Portfolios ---
def list_portfolios() -> list[dict]:
    return _handle(requests.get(_url("/api/portfolios/")))


def create_portfolio(data: dict) -> dict:
    return _handle(requests.post(_url("/api/portfolios/"), json=data))


def delete_portfolio(portfolio_id: int):
    return _handle(requests.delete(_url(f"/api/portfolios/{portfolio_id}")))


def get_portfolio_summary(portfolio_id: int) -> dict:
    return _handle(requests.get(_url(f"/api/portfolios/{portfolio_id}/summary")))


def run_portfolio_monte_carlo(portfolio_id: int, n_iterations: int = 10000,
                               correlation: float = 0.0, seed: int | None = None) -> dict:
    params = {"n_iterations": n_iterations, "correlation": correlation}
    if seed:
        params["seed"] = seed
    return _handle(requests.post(_url(f"/api/portfolios/{portfolio_id}/montecarlo"), params=params))


def get_portfolio_cashflows(portfolio_id: int) -> list[dict]:
    return _handle(requests.get(_url(f"/api/portfolios/{portfolio_id}/cashflows")))


# --- Health ---
def health_check() -> bool:
    try:
        resp = requests.get(_url("/api/health"), timeout=2)
        return resp.status_code == 200
    except Exception:
        return False
