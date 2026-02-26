"""
PharmaPulse MCP Server

Exposes PharmaPulse portfolio intelligence functionality as tools callable by
Claude Desktop or any MCP-compatible client.

Architecture:
  - Uses the mcp Python SDK with stdio transport
  - All tools are thin wrappers around HTTP calls to the FastAPI backend
  - No business logic here -- the backend handles all calculations
  - The FastAPI backend MUST be running at PHARMAPULSE_API_URL

Tool Categories:
  1. Data Queries        — list/search assets, get snapshots, cashflows
  2. NPV Calculations    — deterministic and Monte Carlo
  3. Portfolio Management — create/modify portfolios and projects
  4. Portfolio Simulation — overrides, hypothetical projects, run simulation
  5. Asset Management     — create assets/snapshots, clone
  6. Simulation Families  — kill/accelerate, TA realloc, BD, concentration (Phase G)
  7. Simulation Runs      — save/restore/compare/label runs (v5)

Usage:
  python mcp_server/server.py

Claude Desktop config (claude_desktop_config.json):
  {
    "mcpServers": {
      "pharmapulse": {
        "command": "python",
        "args": ["/absolute/path/to/pharmapulse/mcp_server/server.py"],
        "env": {
          "PHARMAPULSE_API_URL": "http://localhost:8050/api"
        }
      }
    }
  }
"""

import os
import json
import sys
import logging

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.environ.get("PHARMAPULSE_API_URL", "http://localhost:8050/api")

# Logging to stderr (stdout is reserved for MCP JSON-RPC protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("pharmapulse-mcp")

# ---------------------------------------------------------------------------
# MCP Server & HTTP Client
# ---------------------------------------------------------------------------

server = Server("pharmapulse")
http_client = httpx.AsyncClient(base_url=API_URL, timeout=120.0)


async def _api_get(path: str, params: dict = None) -> dict:
    """Make a GET request to the backend API."""
    try:
        resp = await http_client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.ConnectError:
        return {"error": f"Cannot connect to backend at {API_URL}. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


async def _api_post(path: str, json_data: dict = None) -> dict:
    """Make a POST request to the backend API."""
    try:
        resp = await http_client.post(path, json=json_data)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.ConnectError:
        return {"error": f"Cannot connect to backend at {API_URL}. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


async def _api_put(path: str, json_data: dict = None) -> dict:
    """Make a PUT request to the backend API."""
    try:
        resp = await http_client.put(path, json=json_data)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.ConnectError:
        return {"error": f"Cannot connect to backend at {API_URL}. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


async def _api_delete(path: str) -> dict:
    """Make a DELETE request to the backend API."""
    try:
        resp = await http_client.delete(path)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except httpx.ConnectError:
        return {"error": f"Cannot connect to backend at {API_URL}. Is it running?"}
    except Exception as e:
        return {"error": str(e)}


def _text_result(data) -> list[TextContent]:
    """Convert any data to MCP TextContent result."""
    if isinstance(data, (dict, list)):
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    return [TextContent(type="text", text=str(data))]


# ===========================================================================
# TOOL DEFINITIONS
# ===========================================================================

TOOLS = [
    # ---- Category 1: Data Queries ----
    Tool(
        name="list_assets",
        description=(
            "List and filter drug assets in the PharmaPulse database. "
            "Returns all assets by default. Use filters to narrow results. "
            "Use this when the user asks 'show me all projects' or 'list internal assets'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "is_internal": {
                    "type": "boolean",
                    "description": "Filter: true for internal assets only, false for competitors only. Omit for all.",
                },
                "therapeutic_area": {
                    "type": "string",
                    "description": "Filter by therapeutic area (e.g., 'Oncology', 'Neuroscience').",
                },
                "compound_name": {
                    "type": "string",
                    "description": "Partial match filter on compound name.",
                },
                "current_phase": {
                    "type": "string",
                    "description": "Filter by development phase (e.g., 'Phase 1', 'Phase 3').",
                },
                "min_npv": {
                    "type": "number",
                    "description": "Minimum deterministic NPV filter (EUR mm).",
                },
                "max_npv": {
                    "type": "number",
                    "description": "Maximum deterministic NPV filter (EUR mm).",
                },
            },
        },
    ),
    Tool(
        name="get_asset_detail",
        description=(
            "Get detailed information about a specific asset including all its snapshots. "
            "Use this when the user asks about a specific drug/project by name or ID."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID to look up.",
                },
            },
            "required": ["asset_id"],
        },
    ),
    Tool(
        name="get_snapshot_detail",
        description=(
            "Get full snapshot detail with all inputs (phases, R&D costs, commercial data, "
            "MC config) and results (NPV, cashflow summary). Use this when the user asks "
            "about specific valuation assumptions or wants to see how NPV was calculated."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID.",
                },
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID.",
                },
            },
            "required": ["asset_id", "snapshot_id"],
        },
    ),
    Tool(
        name="get_cashflows",
        description=(
            "Get calculated cashflow table for a snapshot. Returns year-by-year revenue, "
            "costs, tax, risk-adjusted FCF, and present values. Use this for detailed "
            "financial analysis or chart data."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID.",
                },
                "scope": {
                    "type": "string",
                    "description": "Filter by scope: 'R&D', 'US', 'EU', etc. Omit for all.",
                },
                "start_year": {
                    "type": "integer",
                    "description": "Start year filter.",
                },
                "end_year": {
                    "type": "integer",
                    "description": "End year filter.",
                },
            },
            "required": ["snapshot_id"],
        },
    ),
    Tool(
        name="search_assets",
        description=(
            "Search assets by compound name, therapeutic area, phase, or NPV range. "
            "Same as list_assets but with the intent of searching. "
            "Use when the user says 'find', 'search', or 'which assets have NPV above X'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "compound_name": {
                    "type": "string",
                    "description": "Partial match on compound name.",
                },
                "therapeutic_area": {
                    "type": "string",
                    "description": "Exact match on therapeutic area.",
                },
                "current_phase": {
                    "type": "string",
                    "description": "Exact match on development phase.",
                },
                "is_internal": {
                    "type": "boolean",
                    "description": "Filter internal/competitor.",
                },
                "min_npv": {
                    "type": "number",
                    "description": "Minimum deterministic NPV (EUR mm).",
                },
                "max_npv": {
                    "type": "number",
                    "description": "Maximum deterministic NPV (EUR mm).",
                },
            },
        },
    ),

    # ---- Category 2: NPV Calculations ----
    Tool(
        name="run_deterministic_npv",
        description=(
            "Run deterministic risk-adjusted NPV calculation for a snapshot. "
            "Calculates rNPV using all financial rules (phases, revenue curves, "
            "discounting, risk adjustment). Stores cashflows and updates the snapshot. "
            "Use this when the user asks to 'calculate NPV' or 'run valuation'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID to calculate NPV for.",
                },
            },
            "required": ["snapshot_id"],
        },
    ),
    Tool(
        name="run_monte_carlo",
        description=(
            "Run Monte Carlo simulation for a snapshot. Runs N iterations with "
            "random variable toggles for success rates, timing, and revenue. "
            "Returns distribution statistics (mean, P10, P50, P90, std dev). "
            "Use this when the user asks for 'Monte Carlo', 'probability distribution', "
            "or 'range of outcomes'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID.",
                },
                "iterations": {
                    "type": "integer",
                    "description": "Number of Monte Carlo iterations (default: 1000).",
                },
            },
            "required": ["snapshot_id"],
        },
    ),

    # ---- Category 3: Portfolio Management ----
    Tool(
        name="list_portfolios",
        description=(
            "List all portfolios with project count, saved runs count, and latest run info. "
            "Use this when the user asks 'show me all portfolios' or 'list my portfolios'. "
            "Returns: id, name, type, project_count, total_npv, saved_runs_count."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="get_portfolio_detail",
        description=(
            "Get full portfolio detail including projects, overrides, added projects, "
            "BD placeholders, and all saved simulation runs. "
            "Use this when the user asks to 'open' or 'show' a specific portfolio."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
            },
            "required": ["portfolio_id"],
        },
    ),
    Tool(
        name="create_portfolio",
        description=(
            "Create a new portfolio. For base portfolios, optionally include asset_ids "
            "to add all projects in one call. For scenario portfolios, base_portfolio_id "
            "is required. Use this when the user says 'create a portfolio' or "
            "'make a new scenario'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Name for the new portfolio.",
                },
                "portfolio_type": {
                    "type": "string",
                    "enum": ["base", "scenario"],
                    "description": "Type: 'base' for baseline, 'scenario' for what-if variant.",
                },
                "base_portfolio_id": {
                    "type": "integer",
                    "description": "Required for scenario portfolios. ID of the base portfolio.",
                },
                "asset_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of asset IDs to add as projects. Use this to bulk-add projects.",
                },
            },
            "required": ["portfolio_name", "portfolio_type"],
        },
    ),
    Tool(
        name="add_project_to_portfolio",
        description=(
            "Add a project (drug asset) to an existing portfolio. "
            "Use when the user says 'add asset X to portfolio Y'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID to add.",
                },
                "snapshot_id": {
                    "type": "integer",
                    "description": "Optional: specific snapshot ID to use. If omitted, latest snapshot is used.",
                },
            },
            "required": ["portfolio_id", "asset_id"],
        },
    ),
    Tool(
        name="remove_project_from_portfolio",
        description=(
            "Remove a project from a portfolio entirely. "
            "Different from cancel/deactivate which keeps the project but sets NPV to 0."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID to remove.",
                },
            },
            "required": ["portfolio_id", "asset_id"],
        },
    ),
    Tool(
        name="cancel_project_in_portfolio",
        description=(
            "Deactivate (kill) a project in a portfolio. Sets the project's NPV contribution "
            "to 0 but keeps it in the portfolio for comparison. Auto-creates a project_kill "
            "override. Only works on scenario portfolios. "
            "Use when the user says 'kill project X' or 'cancel project X'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID (must be scenario type).",
                },
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID to deactivate.",
                },
            },
            "required": ["portfolio_id", "asset_id"],
        },
    ),
    Tool(
        name="reactivate_project_in_portfolio",
        description=(
            "Reactivate a previously cancelled project in a portfolio. "
            "Removes the project_kill override and restores NPV contribution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID to reactivate.",
                },
            },
            "required": ["portfolio_id", "asset_id"],
        },
    ),

    # ---- Category 4: Portfolio Simulation ----
    Tool(
        name="add_portfolio_override",
        description=(
            "Add a scenario override to a project in a portfolio. Override types: "
            "peak_sales_change (% change), sr_override (absolute SR), phase_delay (months), "
            "launch_delay (months), time_to_peak_change (years), accelerate (months), "
            "budget_realloc (multiplier). Only works on scenario portfolios."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "portfolio_project_id": {
                    "type": "integer",
                    "description": "The portfolio project ID (not asset_id).",
                },
                "override_type": {
                    "type": "string",
                    "enum": [
                        "peak_sales_change", "sr_override", "phase_delay",
                        "launch_delay", "time_to_peak_change", "accelerate",
                        "budget_realloc", "project_kill", "project_add", "bd_add",
                    ],
                    "description": "Type of override to apply.",
                },
                "override_value": {
                    "type": "number",
                    "description": "Override value. Meaning depends on type: e.g., +10 for 10% peak sales increase.",
                },
                "phase_name": {
                    "type": "string",
                    "description": "Phase name (required for sr_override, phase_delay, budget_realloc).",
                },
                "description": {
                    "type": "string",
                    "description": "Optional human-readable description of the override.",
                },
            },
            "required": ["portfolio_id", "portfolio_project_id", "override_type", "override_value"],
        },
    ),
    Tool(
        name="remove_portfolio_override",
        description=(
            "Remove a scenario override from a portfolio project."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "override_id": {
                    "type": "integer",
                    "description": "The override ID to remove.",
                },
            },
            "required": ["portfolio_id", "override_id"],
        },
    ),
    Tool(
        name="add_hypothetical_project",
        description=(
            "Add a hypothetical (not yet in pipeline) project to a portfolio for "
            "what-if analysis. Use when the user says 'what if we added a project in Oncology'. "
            "Required fields: portfolio_id, compound_name, current_phase, peak_sales, "
            "time_to_peak_years, approval_date (year as number e.g. 2030), "
            "launch_date (year as number e.g. 2031), loe_year (year as number e.g. 2045), "
            "phases_json (JSON array of phase objects), rd_costs_json (JSON object of year:cost). "
            "Example phases_json: '[{\"phase_name\":\"Phase 2\",\"duration_months\":24,\"success_rate\":0.4,\"cost\":20}]'. "
            "Example rd_costs_json: '{\"2026\":10,\"2027\":15}'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "compound_name": {"type": "string", "description": "Name of the hypothetical compound."},
                "therapeutic_area": {"type": "string", "description": "Therapeutic area (e.g. Oncology)."},
                "indication": {"type": "string", "description": "Target indication."},
                "current_phase": {"type": "string", "description": "Current development phase (e.g. Phase 2)."},
                "peak_sales": {"type": "number", "description": "Estimated peak annual sales (EUR mm)."},
                "time_to_peak_years": {"type": "number", "description": "Years from launch to reach peak sales (e.g. 4)."},
                "approval_date": {"type": "number", "description": "Expected regulatory approval year (e.g. 2030)."},
                "launch_date": {"type": "number", "description": "Expected commercial launch year (e.g. 2031)."},
                "loe_year": {"type": "number", "description": "Loss of exclusivity year (e.g. 2045)."},
                "phases_json": {"type": "string", "description": "JSON array of phase objects: [{\"phase_name\": \"Phase 2\", \"duration_months\": 24, \"success_rate\": 0.4, \"cost\": 20}]."},
                "rd_costs_json": {"type": "string", "description": "JSON object mapping year to annual R&D cost in EUR mm: {\"2026\": 10, \"2027\": 15}."},
                "wacc_rd": {"type": "number", "description": "R&D discount rate (default 0.08)."},
                "wacc_commercial": {"type": "number", "description": "Commercial discount rate (default 0.085)."},
            },
            "required": [
                "portfolio_id", "compound_name", "current_phase", "peak_sales",
                "time_to_peak_years", "approval_date", "launch_date", "loe_year",
                "phases_json", "rd_costs_json",
            ],
        },
    ),
    Tool(
        name="run_portfolio_simulation",
        description=(
            "Run portfolio simulation. Calculates NPV for all projects in the portfolio, "
            "applies all overrides, adds hypothetical projects and BD placeholders, "
            "and aggregates portfolio totals. "
            "Use this after adding overrides or when the user says 'simulate the portfolio'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID to simulate.",
                },
            },
            "required": ["portfolio_id"],
        },
    ),
    Tool(
        name="compare_portfolios",
        description=(
            "Compare two portfolios side-by-side. Returns NPV delta and percentage change. "
            "Use when the user asks 'compare portfolio A with B' or 'what changed between base and scenario'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id_a": {
                    "type": "integer",
                    "description": "First portfolio ID.",
                },
                "portfolio_id_b": {
                    "type": "integer",
                    "description": "Second portfolio ID.",
                },
            },
            "required": ["portfolio_id_a", "portfolio_id_b"],
        },
    ),
    Tool(
        name="get_portfolio_summary",
        description=(
            "Get a concise portfolio summary optimized for quick reading. "
            "Returns portfolio name, type, total NPV, project count, "
            "and per-project NPV with status. Lighter than get_portfolio_detail."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
            },
            "required": ["portfolio_id"],
        },
    ),

    # ---- Category 5: Asset Management ----
    Tool(
        name="create_asset",
        description=(
            "Create a new drug asset in the database. "
            "Use when the user says 'add a new drug' or 'create a new asset entry'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sponsor": {"type": "string", "description": "Sponsor company name."},
                "compound_name": {"type": "string", "description": "Drug compound name / code."},
                "moa": {"type": "string", "description": "Mechanism of action."},
                "therapeutic_area": {"type": "string", "description": "Therapeutic area."},
                "indication": {"type": "string", "description": "Target indication."},
                "current_phase": {"type": "string", "description": "Current development phase."},
                "is_internal": {"type": "boolean", "description": "True for internal, false for competitor."},
                "peak_sales_estimate": {"type": "number", "description": "Estimated peak sales (EUR mm)."},
                "launch_date": {"type": "string", "description": "Expected launch date (YYYY or YYYY-MM-DD)."},
            },
            "required": ["sponsor", "compound_name", "moa", "therapeutic_area", "indication", "current_phase", "is_internal"],
        },
    ),
    Tool(
        name="create_snapshot",
        description=(
            "Create a new valuation snapshot for an asset. A snapshot captures all "
            "valuation inputs at a point in time. Use clone_snapshot instead if you "
            "want to copy from an existing snapshot."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "integer", "description": "The asset ID."},
                "snapshot_name": {"type": "string", "description": "Name for this snapshot."},
                "description": {"type": "string", "description": "Optional description."},
                "valuation_year": {"type": "integer", "description": "Valuation year (default: 2025)."},
                "horizon_years": {"type": "integer", "description": "Projection horizon (default: 20)."},
                "wacc_rd": {"type": "number", "description": "R&D WACC rate (default: 0.08)."},
            },
            "required": ["asset_id", "snapshot_name"],
        },
    ),
    Tool(
        name="clone_snapshot",
        description=(
            "Clone an existing snapshot. Creates a deep copy of all inputs "
            "(phases, costs, commercial data, MC config). "
            "Use when the user wants to create a variant of an existing valuation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "asset_id": {"type": "integer", "description": "The asset ID."},
                "snapshot_id": {"type": "integer", "description": "The snapshot ID to clone."},
                "new_name": {"type": "string", "description": "Name for the cloned snapshot."},
            },
            "required": ["asset_id", "snapshot_id"],
        },
    ),

    # ---- Category 6: Simulation Families (Phase G endpoints) ----
    Tool(
        name="analyze_kill_impact",
        description=(
            "Analyze the financial impact of killing a project: NPV lost, R&D budget freed, "
            "portfolio NPV before/after, and a recommendation. Read-only analysis — does NOT "
            "actually kill the project. Use cancel_project_in_portfolio to actually kill it. "
            "Part of Family A (Kill/Continue/Accelerate)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset to analyze killing."},
            },
            "required": ["portfolio_id", "asset_id"],
        },
    ),
    Tool(
        name="analyze_acceleration",
        description=(
            "Analyze the impact of accelerating a project by increasing R&D budget. "
            "Returns months saved, extra cost, NPV gain, and acceleration curve. "
            "Part of Family A (Kill/Continue/Accelerate)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset to accelerate."},
                "budget_multiplier": {
                    "type": "number",
                    "description": "R&D budget multiplier (1.0 = no change, 1.5 = 50% more budget, max 2.0). Default 1.5.",
                },
                "phase_name": {
                    "type": "string",
                    "description": "Phase to accelerate (e.g. 'Phase 2', 'Phase 3'). If omitted, uses current phase.",
                },
            },
            "required": ["portfolio_id", "asset_id"],
        },
    ),
    Tool(
        name="get_ta_budget_distribution",
        description=(
            "Get current therapeutic area budget distribution for a portfolio. "
            "Returns NPV, R&D cost, efficiency (NPV per EUR mm), and project counts per TA. "
            "Part of Family B (TA Budget Reallocation)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    ),
    Tool(
        name="get_temporal_balance",
        description=(
            "Get launch timeline for all projects in a portfolio. "
            "Maps estimated launch years based on current development phase. "
            "Use to identify patent cliffs and pipeline gaps. "
            "Part of Family C (Temporal Balance)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    ),
    Tool(
        name="get_innovation_risk_charter",
        description=(
            "Get risk-return scatter plot data for all projects in a portfolio. "
            "X=Risk (1-PTS), Y=NPV, with quadrant classification. "
            "Part of Family D (Innovation vs Risk Charter)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    ),
    Tool(
        name="analyze_bd_deal",
        description=(
            "Value a business development deal (in-licensing or acquisition). "
            "Computes risk-adjusted NPV from deal economics: upfront cost, peak sales, "
            "market share, margin, timeline, milestones, royalties. "
            "Standalone financial valuation — no portfolio context needed. "
            "Part of Family E (BD Cut & Reinvest)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "peak_sales": {
                    "type": "number",
                    "description": "Expected peak annual sales for the asset (EUR mm).",
                },
                "market_share_pct": {
                    "type": "number",
                    "description": "Expected market share percentage (e.g. 30 for 30%).",
                },
                "margin_pct": {
                    "type": "number",
                    "description": "Operating margin percentage (default 70).",
                },
                "years_to_launch": {
                    "type": "integer",
                    "description": "Years from now to expected commercial launch.",
                },
                "commercial_duration_years": {
                    "type": "integer",
                    "description": "Years of commercial exclusivity (default 10).",
                },
                "upfront_payment": {
                    "type": "number",
                    "description": "Upfront payment / acquisition cost (EUR mm).",
                },
                "milestones_eur_mm": {
                    "type": "number",
                    "description": "Total milestone payments (EUR mm, default 0).",
                },
                "royalty_pct": {
                    "type": "number",
                    "description": "Royalty percentage to licensor (default 0).",
                },
                "wacc": {
                    "type": "number",
                    "description": "Discount rate for the deal (default 0.10).",
                },
                "pts": {
                    "type": "number",
                    "description": "Probability of technical success (0-1, default 0.5).",
                },
            },
            "required": ["peak_sales", "market_share_pct", "years_to_launch", "upfront_payment"],
        },
    ),
    Tool(
        name="save_bd_placeholder",
        description=(
            "Save a BD placeholder to a portfolio. Creates the BD entry and associated override."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "deal_name": {"type": "string", "description": "Name of the BD deal."},
                "deal_type": {"type": "string", "description": "Deal type."},
                "therapeutic_area": {"type": "string", "description": "Therapeutic area."},
                "current_phase": {"type": "string", "description": "Current phase."},
                "peak_sales": {"type": "number", "description": "Peak sales (EUR mm)."},
                "upfront_payment": {"type": "number", "description": "Upfront payment (EUR mm)."},
            },
            "required": ["portfolio_id", "deal_name", "deal_type", "peak_sales"],
        },
    ),
    Tool(
        name="get_concentration_analysis",
        description=(
            "Analyze portfolio concentration risk using HHI (Herfindahl-Hirschman Index) "
            "across project, therapeutic area, and phase dimensions. "
            "Flags high-concentration areas. Part of Family F (Concentration Risk)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    ),

    # ---- Category 7: Simulation Run Management (v5) ----
    Tool(
        name="save_simulation_run",
        description=(
            "Save the current portfolio simulation state as a named, immutable run. "
            "Captures all overrides, results, deactivated assets, and totals for audit trail. "
            "Requires that simulation has been run first (portfolio_results must exist). "
            "Use after running a simulation when the user says 'save this' or 'bookmark this state'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "run_name": {
                    "type": "string",
                    "description": "Name for the saved run (e.g., 'Baseline Q1 2026', 'Option A').",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about this simulation run.",
                },
            },
            "required": ["portfolio_id", "run_name"],
        },
    ),
    Tool(
        name="list_simulation_runs",
        description=(
            "List all saved simulation runs for a portfolio, newest first. "
            "Returns run_id, name, total_npv, timestamp, notes, and override count."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
            },
            "required": ["portfolio_id"],
        },
    ),
    Tool(
        name="get_simulation_run_detail",
        description=(
            "Get full detail of a saved simulation run including frozen overrides, "
            "per-project results, added projects, and BD placeholders. "
            "Use to inspect exactly what was configured in a past simulation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "run_id": {
                    "type": "integer",
                    "description": "The run ID.",
                },
            },
            "required": ["portfolio_id", "run_id"],
        },
    ),
    Tool(
        name="compare_simulation_runs",
        description=(
            "Compare two saved simulation runs side-by-side. Returns total NPV delta, "
            "percentage change, and per-asset comparison. Runs can be from the same "
            "or different portfolios. "
            "Use when the user asks 'compare Option A vs Option B'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "run_id_a": {
                    "type": "integer",
                    "description": "First run ID.",
                },
                "run_id_b": {
                    "type": "integer",
                    "description": "Second run ID.",
                },
            },
            "required": ["run_id_a", "run_id_b"],
        },
    ),
    Tool(
        name="restore_simulation_run",
        description=(
            "Restore overrides from a saved simulation run as the current working state. "
            "The saved run itself is unchanged (immutable). Only the current mutable "
            "override state is replaced. Then re-runs simulation with restored overrides. "
            "Use when the user says 'go back to Option A' or 'restore that run'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "run_id": {
                    "type": "integer",
                    "description": "The run ID to restore from.",
                },
            },
            "required": ["portfolio_id", "run_id"],
        },
    ),
    Tool(
        name="label_simulation_run",
        description=(
            "Update a simulation run's name or notes. "
            "Use when the user says 'rename that run' or 'add notes to the last run'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
                "run_id": {
                    "type": "integer",
                    "description": "The run ID to update.",
                },
                "run_name": {
                    "type": "string",
                    "description": "New name (optional, omit to keep current).",
                },
                "notes": {
                    "type": "string",
                    "description": "New notes (optional, omit to keep current).",
                },
            },
            "required": ["portfolio_id", "run_id"],
        },
    ),
]


# ===========================================================================
# TOOL HANDLERS
# ===========================================================================

@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """Return all available MCP tools."""
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Route MCP tool calls to the appropriate backend API endpoint.
    Each handler is a thin adapter: extract args → HTTP call → return JSON.
    """
    logger.info(f"Tool call: {name} with args: {json.dumps(arguments, default=str)}")

    try:
        result = await _dispatch_tool(name, arguments)
        return _text_result(result)
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return _text_result({"error": str(e)})


async def _dispatch_tool(name: str, args: dict) -> dict:
    """Dispatch a tool call to the appropriate API endpoint."""

    # ---- Category 1: Data Queries ----

    if name == "list_assets":
        params = {}
        if args.get("is_internal") is not None:
            params["is_internal"] = str(args["is_internal"]).lower()
        if args.get("therapeutic_area"):
            params["therapeutic_area"] = args["therapeutic_area"]
        if args.get("compound_name"):
            params["compound_name"] = args["compound_name"]
        if args.get("current_phase"):
            params["current_phase"] = args["current_phase"]
        if args.get("min_npv") is not None:
            params["min_npv"] = args["min_npv"]
        if args.get("max_npv") is not None:
            params["max_npv"] = args["max_npv"]
        return await _api_get("/query/assets", params=params)

    elif name == "get_asset_detail":
        asset_id = args["asset_id"]
        # Get asset info + list snapshots
        asset_info = await _api_get(f"/portfolio")
        if isinstance(asset_info, list):
            asset = next((a for a in asset_info if a.get("id") == asset_id), None)
            if not asset:
                return {"error": f"Asset {asset_id} not found"}
        else:
            asset = asset_info
        snapshots = await _api_get(f"/snapshots/{asset_id}")
        return {"asset": asset, "snapshots": snapshots}

    elif name == "get_snapshot_detail":
        return await _api_get(
            f"/snapshots/{args['asset_id']}/{args['snapshot_id']}"
        )

    elif name == "get_cashflows":
        params = {}
        if args.get("scope"):
            params["scope"] = args["scope"]
        if args.get("start_year"):
            params["start_year"] = args["start_year"]
        if args.get("end_year"):
            params["end_year"] = args["end_year"]
        return await _api_get(
            f"/query/cashflows/{args['snapshot_id']}", params=params
        )

    elif name == "search_assets":
        params = {}
        for key in ("compound_name", "therapeutic_area", "current_phase",
                     "min_npv", "max_npv"):
            if args.get(key) is not None:
                params[key] = args[key]
        if args.get("is_internal") is not None:
            params["is_internal"] = str(args["is_internal"]).lower()
        return await _api_get("/query/assets", params=params)

    # ---- Category 2: NPV Calculations ----

    elif name == "run_deterministic_npv":
        return await _api_post(
            f"/npv/deterministic/{args['snapshot_id']}"
        )

    elif name == "run_monte_carlo":
        params = {}
        if args.get("iterations"):
            params["iterations"] = args["iterations"]
        return await _api_post(
            f"/npv/montecarlo/{args['snapshot_id']}", json_data=params or None
        )

    # ---- Category 3: Portfolio Management ----

    elif name == "list_portfolios":
        return await _api_get("/portfolios")

    elif name == "get_portfolio_detail":
        return await _api_get(f"/portfolios/{args['portfolio_id']}")

    elif name == "create_portfolio":
        data = {
            "portfolio_name": args["portfolio_name"],
            "portfolio_type": args["portfolio_type"],
        }
        if args.get("base_portfolio_id"):
            data["base_portfolio_id"] = args["base_portfolio_id"]
        if args.get("asset_ids"):
            data["asset_ids"] = args["asset_ids"]
        return await _api_post("/portfolios", json_data=data)

    elif name == "add_project_to_portfolio":
        data = {"asset_id": args["asset_id"]}
        if args.get("snapshot_id"):
            data["snapshot_id"] = args["snapshot_id"]
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/projects",
            json_data=data,
        )

    elif name == "remove_project_from_portfolio":
        return await _api_delete(
            f"/portfolios/{args['portfolio_id']}/projects/{args['asset_id']}"
        )

    elif name == "cancel_project_in_portfolio":
        return await _api_put(
            f"/portfolios/{args['portfolio_id']}/projects/{args['asset_id']}/deactivate"
        )

    elif name == "reactivate_project_in_portfolio":
        return await _api_put(
            f"/portfolios/{args['portfolio_id']}/projects/{args['asset_id']}/activate"
        )

    # ---- Category 4: Portfolio Simulation ----

    elif name == "add_portfolio_override":
        data = {
            "portfolio_project_id": args["portfolio_project_id"],
            "override_type": args["override_type"],
            "override_value": args["override_value"],
        }
        if args.get("phase_name"):
            data["phase_name"] = args["phase_name"]
        if args.get("description"):
            data["description"] = args["description"]
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/overrides",
            json_data=data,
        )

    elif name == "remove_portfolio_override":
        return await _api_delete(
            f"/portfolios/{args['portfolio_id']}/overrides/{args['override_id']}"
        )

    elif name == "add_hypothetical_project":
        data = {
            "compound_name": args["compound_name"],
            "current_phase": args["current_phase"],
            "peak_sales": args["peak_sales"],
            "time_to_peak_years": args["time_to_peak_years"],
            "approval_date": args["approval_date"],
            "launch_date": args["launch_date"],
            "loe_year": args["loe_year"],
            "phases_json": args["phases_json"],
            "rd_costs_json": args["rd_costs_json"],
        }
        # Optional fields
        for key in ("therapeutic_area", "indication", "wacc_rd", "wacc_commercial"):
            if args.get(key) is not None:
                data[key] = args[key]
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/added-projects",
            json_data=data,
        )

    elif name == "run_portfolio_simulation":
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/simulate"
        )

    elif name == "compare_portfolios":
        return await _api_get(
            "/portfolios/compare",
            params={"ids": f"{args['portfolio_id_a']},{args['portfolio_id_b']}"},
        )

    elif name == "get_portfolio_summary":
        return await _api_get(
            f"/query/portfolio-summary/{args['portfolio_id']}"
        )

    # ---- Category 5: Asset Management ----

    elif name == "create_asset":
        data = {
            "sponsor": args["sponsor"],
            "compound_name": args["compound_name"],
            "moa": args["moa"],
            "therapeutic_area": args["therapeutic_area"],
            "indication": args["indication"],
            "current_phase": args["current_phase"],
            "is_internal": args["is_internal"],
        }
        if args.get("peak_sales_estimate") is not None:
            data["peak_sales_estimate"] = args["peak_sales_estimate"]
        if args.get("launch_date"):
            data["launch_date"] = args["launch_date"]
        return await _api_post("/portfolio", json_data=data)

    elif name == "create_snapshot":
        data = {"snapshot_name": args["snapshot_name"]}
        for key in ("description", "valuation_year", "horizon_years", "wacc_rd"):
            if args.get(key) is not None:
                data[key] = args[key]
        return await _api_post(
            f"/snapshots/{args['asset_id']}", json_data=data
        )

    elif name == "clone_snapshot":
        params = {}
        if args.get("new_name"):
            params["new_name"] = args["new_name"]
        return await _api_post(
            f"/snapshots/{args['asset_id']}/{args['snapshot_id']}/clone",
            json_data=params or None,
        )

    # ---- Category 6: Simulation Families (Phase G) ----
    # Backend routes: /api/simulations/family-{A..F}/...

    elif name == "analyze_kill_impact":
        # GET /api/simulations/family-a/kill/{portfolio_id}/{asset_id}
        pid = args["portfolio_id"]
        aid = args["asset_id"]
        return await _api_get(f"/simulations/family-a/kill/{pid}/{aid}")

    elif name == "analyze_acceleration":
        # POST /api/simulations/family-a/accelerate/{portfolio_id}/{asset_id}
        # Body: AccelerationRequest { budget_multiplier, phase_name }
        pid = args["portfolio_id"]
        aid = args["asset_id"]
        data = {
            "budget_multiplier": args.get("budget_multiplier", 1.5),
        }
        if args.get("phase_name"):
            data["phase_name"] = args["phase_name"]
        return await _api_post(
            f"/simulations/family-a/accelerate/{pid}/{aid}",
            json_data=data,
        )

    elif name == "get_ta_budget_distribution":
        # GET /api/simulations/family-b/ta-summary/{portfolio_id}
        pid = args["portfolio_id"]
        return await _api_get(f"/simulations/family-b/ta-summary/{pid}")

    elif name == "get_temporal_balance":
        # GET /api/simulations/family-c/launch-timeline/{portfolio_id}
        pid = args["portfolio_id"]
        return await _api_get(f"/simulations/family-c/launch-timeline/{pid}")

    elif name == "get_innovation_risk_charter":
        # GET /api/simulations/family-d/risk-return/{portfolio_id}
        pid = args["portfolio_id"]
        return await _api_get(f"/simulations/family-d/risk-return/{pid}")

    elif name == "analyze_bd_deal":
        # POST /api/simulations/family-e/value-deal
        # Body: BDDealRequest { peak_sales_eur_mm, market_share_pct,
        #   margin_pct, years_to_launch, commercial_duration_years,
        #   upfront_eur_mm, milestones_eur_mm, royalty_pct, wacc, pts }
        data = {
            "peak_sales_eur_mm": args.get("peak_sales", 500.0),
            "market_share_pct": args.get("market_share_pct", 30.0),
            "margin_pct": args.get("margin_pct", 70.0),
            "years_to_launch": args.get("years_to_launch", 3),
            "commercial_duration_years": args.get("commercial_duration_years", 10),
            "upfront_eur_mm": args.get("upfront_payment", 100.0),
            "milestones_eur_mm": args.get("milestones_eur_mm", 0.0),
            "royalty_pct": args.get("royalty_pct", 0.0),
            "wacc": args.get("wacc", 0.10),
            "pts": args.get("pts", 0.5),
        }
        return await _api_post("/simulations/family-e/value-deal", json_data=data)

    elif name == "save_bd_placeholder":
        data = {
            "deal_name": args["deal_name"],
            "deal_type": args["deal_type"],
            "peak_sales": args["peak_sales"],
        }
        for key in ("therapeutic_area", "current_phase", "upfront_payment"):
            if args.get(key) is not None:
                data[key] = args[key]
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/bd-placeholders",
            json_data=data,
        )

    elif name == "get_concentration_analysis":
        # GET /api/simulations/family-f/hhi/{portfolio_id}
        pid = args["portfolio_id"]
        return await _api_get(f"/simulations/family-f/hhi/{pid}")

    # ---- Category 7: Simulation Run Management (v5) ----

    elif name == "save_simulation_run":
        data = {"run_name": args["run_name"]}
        if args.get("notes"):
            data["notes"] = args["notes"]
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/runs",
            json_data=data,
        )

    elif name == "list_simulation_runs":
        return await _api_get(
            f"/portfolios/{args['portfolio_id']}/runs"
        )

    elif name == "get_simulation_run_detail":
        return await _api_get(
            f"/portfolios/{args['portfolio_id']}/runs/{args['run_id']}"
        )

    elif name == "compare_simulation_runs":
        return await _api_get(
            "/portfolios/compare-runs",
            params={"run_ids": f"{args['run_id_a']},{args['run_id_b']}"},
        )

    elif name == "restore_simulation_run":
        return await _api_post(
            f"/portfolios/{args['portfolio_id']}/runs/{args['run_id']}/restore"
        )

    elif name == "label_simulation_run":
        data = {}
        if args.get("run_name"):
            data["run_name"] = args["run_name"]
        if args.get("notes"):
            data["notes"] = args["notes"]
        return await _api_put(
            f"/portfolios/{args['portfolio_id']}/runs/{args['run_id']}",
            json_data=data,
        )

    else:
        return {"error": f"Unknown tool: {name}"}


# ===========================================================================
# ENTRY POINT
# ===========================================================================

async def main():
    """Start the MCP server using stdio transport."""
    logger.info(f"PharmaPulse MCP Server starting. Backend: {API_URL}")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())


