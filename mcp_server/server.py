"""PharmaPulse MCP Server — exposes portfolio tools for AI agents.

Provides tools to query assets, snapshots, run NPV calculations,
and interact with the portfolio via the Model Context Protocol.

Usage:
    python -m mcp.server
    # or
    python mcp/server.py
"""

import json
import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = "http://localhost:8000"

mcp = FastMCP(
    "PharmaPulse",
    description="Pharma R&D Portfolio NPV Platform — query assets, run NPV, and analyze portfolios",
)


def _api(method: str, path: str, **kwargs) -> dict | list:
    """Make a synchronous API call to the PharmaPulse backend."""
    url = f"{API_BASE}{path}"
    with httpx.Client(timeout=60) as client:
        if method == "GET":
            resp = client.get(url, params=kwargs.get("params"))
        elif method == "POST":
            resp = client.post(url, json=kwargs.get("json"), params=kwargs.get("params"))
        elif method == "PUT":
            resp = client.put(url, json=kwargs.get("json"))
        elif method == "DELETE":
            resp = client.delete(url)
        else:
            raise ValueError(f"Unknown method: {method}")

    if resp.status_code >= 400:
        return {"error": f"API returned {resp.status_code}: {resp.text}"}
    return resp.json()


# ============ TOOLS ============

@mcp.tool()
def list_assets() -> str:
    """List all pharma assets in the portfolio with their IDs, therapeutic areas, and phases."""
    assets = _api("GET", "/api/assets/")
    if isinstance(assets, dict) and "error" in assets:
        return json.dumps(assets)

    lines = []
    for a in assets:
        lines.append(
            f"ID:{a['id']} | {a['name']} | TA:{a['therapeutic_area']} | "
            f"Phase:{a['current_phase']} | {'Internal' if a['is_internal'] else 'Licensed'}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_asset_detail(asset_id: int) -> str:
    """Get detailed information about a specific asset including its snapshots and NPV data."""
    asset = _api("GET", f"/api/assets/{asset_id}")
    if isinstance(asset, dict) and "error" in asset:
        return json.dumps(asset)

    snapshots = _api("GET", f"/api/snapshots/asset/{asset_id}")
    result = {
        "asset": asset,
        "snapshots": len(snapshots) if isinstance(snapshots, list) else 0,
    }

    if isinstance(snapshots, list) and snapshots:
        latest = snapshots[-1]
        result["latest_snapshot"] = {
            "id": latest["id"],
            "label": latest["label"],
            "version": latest["version"],
            "peak_sales_usd_m": latest["peak_sales_usd_m"],
            "launch_year": latest["launch_year"],
            "discount_rate": latest["discount_rate"],
        }
        if latest.get("cashflows"):
            cfs = latest["cashflows"]
            result["enpv_usd_m"] = cfs[-1]["cumulative_npv_usd_m"]

        if latest.get("phase_inputs"):
            cum_pos = 1.0
            for pi in latest["phase_inputs"]:
                cum_pos *= pi["probability_of_success"]
            result["cumulative_pos"] = round(cum_pos, 4)

    return json.dumps(result, indent=2)


@mcp.tool()
def run_npv(snapshot_id: int) -> str:
    """Run deterministic risk-adjusted NPV calculation for a snapshot. Returns eNPV, cPOS, and key metrics."""
    result = _api("POST", f"/api/npv/deterministic/{snapshot_id}")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result)

    # Summarize without full cashflow list
    summary = {
        "snapshot_id": result["snapshot_id"],
        "enpv_usd_m": result["enpv_usd_m"],
        "risk_adjusted_npv_usd_m": result["risk_adjusted_npv_usd_m"],
        "unadjusted_npv_usd_m": result["unadjusted_npv_usd_m"],
        "cumulative_pos": result["cumulative_pos"],
        "peak_sales_usd_m": result["peak_sales_usd_m"],
        "launch_year": result["launch_year"],
        "num_cashflow_years": len(result.get("cashflows", [])),
    }
    return json.dumps(summary, indent=2)


@mcp.tool()
def run_monte_carlo(snapshot_id: int) -> str:
    """Run Monte Carlo simulation for a snapshot. Returns distribution statistics (mean, median, percentiles)."""
    result = _api("POST", f"/api/mc/run/{snapshot_id}")
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result)

    # Return stats without full histogram
    summary = {k: v for k, v in result.items() if k != "histogram_data"}
    return json.dumps(summary, indent=2)


@mcp.tool()
def portfolio_summary(portfolio_id: int) -> str:
    """Get portfolio-level summary with total eNPV, asset breakdown, and diversification metrics."""
    result = _api("GET", f"/api/portfolios/{portfolio_id}/summary")
    return json.dumps(result, indent=2)


@mcp.tool()
def run_portfolio_monte_carlo(portfolio_id: int, n_iterations: int = 10000, correlation: float = 0.0) -> str:
    """Run portfolio-level Monte Carlo simulation with optional inter-asset correlation."""
    result = _api("POST", f"/api/portfolios/{portfolio_id}/montecarlo",
                  params={"n_iterations": n_iterations, "correlation": correlation})
    summary = {k: v for k, v in result.items() if k != "histogram_data"}
    return json.dumps(summary, indent=2)


@mcp.tool()
def compare_snapshots(snapshot_id_a: int, snapshot_id_b: int) -> str:
    """Compare two snapshots side by side. Returns key parameter differences and NPV delta."""
    snap_a = _api("GET", f"/api/snapshots/{snapshot_id_a}")
    snap_b = _api("GET", f"/api/snapshots/{snapshot_id_b}")

    if isinstance(snap_a, dict) and "error" in snap_a:
        return json.dumps(snap_a)
    if isinstance(snap_b, dict) and "error" in snap_b:
        return json.dumps(snap_b)

    compare_fields = [
        "peak_sales_usd_m", "launch_year", "patent_expiry_year",
        "discount_rate", "cogs_pct", "sga_pct", "tax_rate",
        "generic_erosion_pct", "uptake_curve",
    ]

    differences = {}
    for f in compare_fields:
        va = snap_a.get(f)
        vb = snap_b.get(f)
        if va != vb:
            differences[f] = {"snapshot_a": va, "snapshot_b": vb}

    enpv_a = None
    enpv_b = None
    if snap_a.get("cashflows"):
        enpv_a = snap_a["cashflows"][-1]["cumulative_npv_usd_m"]
    if snap_b.get("cashflows"):
        enpv_b = snap_b["cashflows"][-1]["cumulative_npv_usd_m"]

    return json.dumps({
        "snapshot_a": {"id": snap_a["id"], "label": snap_a["label"], "enpv": enpv_a},
        "snapshot_b": {"id": snap_b["id"], "label": snap_b["label"], "enpv": enpv_b},
        "enpv_delta": round(enpv_a - enpv_b, 2) if enpv_a and enpv_b else None,
        "parameter_differences": differences,
    }, indent=2)


@mcp.tool()
def create_snapshot(
    asset_id: int,
    label: str = "New Scenario",
    peak_sales_usd_m: float = 500.0,
    launch_year: int = 2030,
    patent_expiry_year: int = 2040,
    discount_rate: float = 0.10,
) -> str:
    """Create a new snapshot for an asset with basic parameters. Returns the snapshot ID."""
    data = {
        "asset_id": asset_id,
        "label": label,
        "peak_sales_usd_m": peak_sales_usd_m,
        "launch_year": launch_year,
        "patent_expiry_year": patent_expiry_year,
        "discount_rate": discount_rate,
    }
    result = _api("POST", "/api/snapshots/", json=data)
    if isinstance(result, dict) and "error" in result:
        return json.dumps(result)
    return json.dumps({"snapshot_id": result["id"], "version": result["version"], "label": result["label"]})


@mcp.tool()
def search_assets(query: str) -> str:
    """Search assets by name, therapeutic area, or indication. Returns matching assets."""
    assets = _api("GET", "/api/assets/")
    if isinstance(assets, dict) and "error" in assets:
        return json.dumps(assets)

    q = query.lower()
    matches = [
        a for a in assets
        if q in a["name"].lower()
        or q in a["therapeutic_area"].lower()
        or q in a["indication"].lower()
        or q in a["molecule_type"].lower()
    ]

    if not matches:
        return f"No assets found matching '{query}'"

    lines = []
    for a in matches:
        lines.append(f"ID:{a['id']} | {a['name']} | {a['therapeutic_area']} | {a['indication']} | {a['current_phase']}")
    return "\n".join(lines)


# ============ RESOURCES ============

@mcp.resource("pharmapulse://portfolio/summary")
def portfolio_overview_resource() -> str:
    """Current portfolio overview with all assets and their NPV status."""
    assets = _api("GET", "/api/assets/")
    if isinstance(assets, dict) and "error" in assets:
        return json.dumps(assets)

    lines = ["# PharmaPulse Portfolio Overview\n"]
    total_enpv = 0

    for a in assets:
        snaps = _api("GET", f"/api/snapshots/asset/{a['id']}")
        latest = snaps[-1] if isinstance(snaps, list) and snaps else None

        line = f"## {a['name']}\n- TA: {a['therapeutic_area']}, Phase: {a['current_phase']}"
        if latest and latest.get("cashflows"):
            enpv = latest["cashflows"][-1]["cumulative_npv_usd_m"]
            line += f"\n- eNPV: ${enpv:,.1f}M, Peak Sales: ${latest['peak_sales_usd_m']:,.0f}M"
            total_enpv += enpv
        lines.append(line)

    lines.append(f"\n## Total Portfolio eNPV: ${total_enpv:,.1f}M")
    return "\n\n".join(lines)


if __name__ == "__main__":
    mcp.run()
