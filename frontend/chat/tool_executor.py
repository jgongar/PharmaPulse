"""
PharmaPulse — Tool Executor

Routes LLM tool calls to the appropriate backend API endpoints using
the existing api_client. This is the bridge between the LLM's function
calling output and the PharmaPulse backend.

Flow:
  1. LLM produces a ToolCall (name + arguments)
  2. execute_tool() dispatches to the correct API method
  3. Result is returned as a dict that gets fed back to the LLM

All tool names match both the tool_definitions.py and the MCP server.
"""

import json
import logging
from typing import Any

from frontend.api_client import api

logger = logging.getLogger("pharmapulse.chat.executor")


def execute_tool(tool_name: str, arguments: dict) -> dict[str, Any]:
    """
    Execute a tool call by dispatching to the backend API.

    Args:
        tool_name: The tool name from the LLM tool call
        arguments: The arguments dict from the LLM

    Returns:
        A dict containing the tool result (or error)
    """
    logger.info(f"Executing tool: {tool_name} with args: {json.dumps(arguments, default=str)}")

    try:
        result = _dispatch(tool_name, arguments)
        return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.error(f"Tool execution error ({tool_name}): {e}")
        return {"error": str(e)}


def _dispatch(name: str, args: dict) -> Any:
    """Dispatch a tool call to the appropriate API method."""

    # ===== Category 1: Data Queries =====

    if name == "list_assets":
        return api.get_assets(
            is_internal=args.get("is_internal"),
            therapeutic_area=args.get("therapeutic_area"),
        )

    elif name == "get_asset_detail":
        asset = api.get_asset(args["asset_id"])
        snapshots = api.get_snapshots(args["asset_id"])
        return {"asset": asset, "snapshots": snapshots}

    elif name == "get_snapshot_detail":
        return api.get_snapshot_detail(args["snapshot_id"])

    elif name == "get_cashflows":
        return api.get_cashflows(
            snapshot_id=args["snapshot_id"],
            scope=args.get("scope"),
        )

    elif name == "search_assets":
        params = {}
        for key in ("compound_name", "therapeutic_area", "current_phase",
                     "min_npv", "max_npv"):
            if args.get(key) is not None:
                params[key] = args[key]
        if args.get("is_internal") is not None:
            params["is_internal"] = args["is_internal"]
        return api.query_assets(**params)

    # ===== Category 2: NPV Calculations =====

    elif name == "run_deterministic_npv":
        return api.run_deterministic_npv(args["snapshot_id"])

    elif name == "run_monte_carlo":
        return api.run_monte_carlo(args["snapshot_id"])

    # ===== Category 3: Portfolio Management =====

    elif name == "list_portfolios":
        return {"portfolios": api.get_portfolios()}

    elif name == "get_portfolio_detail":
        return api.get_portfolio(args["portfolio_id"])

    elif name == "create_portfolio":
        data = {
            "portfolio_name": args["portfolio_name"],
            "portfolio_type": args["portfolio_type"],
        }
        if args.get("base_portfolio_id"):
            data["base_portfolio_id"] = args["base_portfolio_id"]
        if args.get("asset_ids"):
            data["asset_ids"] = args["asset_ids"]
        return api.create_portfolio(data)

    elif name == "add_project_to_portfolio":
        return api._post(
            f"/api/portfolios/{args['portfolio_id']}/projects",
            json_data={"asset_id": args["asset_id"]},
        )

    elif name == "remove_project_from_portfolio":
        return api._delete(
            f"/api/portfolios/{args['portfolio_id']}/projects/{args['asset_id']}"
        )

    elif name == "cancel_project_in_portfolio":
        return api._put(
            f"/api/portfolios/{args['portfolio_id']}/projects/{args['asset_id']}/deactivate"
        )

    elif name == "reactivate_project_in_portfolio":
        return api._put(
            f"/api/portfolios/{args['portfolio_id']}/projects/{args['asset_id']}/activate"
        )

    # ===== Category 4: Portfolio Simulation =====

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
        return api._post(
            f"/api/portfolios/{args['portfolio_id']}/overrides",
            json_data=data,
        )

    elif name == "remove_portfolio_override":
        return api._delete(
            f"/api/portfolios/{args['portfolio_id']}/overrides/{args['override_id']}"
        )

    elif name == "add_hypothetical_project":
        data = {
            "compound_name": args["compound_name"],
            "therapeutic_area": args["therapeutic_area"],
            "indication": args["indication"],
            "current_phase": args["current_phase"],
            "peak_sales": args["peak_sales"],
        }
        for key in ("launch_date", "loe_year", "time_to_peak_years"):
            if args.get(key) is not None:
                data[key] = args[key]
        return api._post(
            f"/api/portfolios/{args['portfolio_id']}/added-projects",
            json_data=data,
        )

    elif name == "run_portfolio_simulation":
        return api.simulate_portfolio(args["portfolio_id"])

    elif name == "compare_portfolios":
        return api._get(
            "/api/portfolios/compare",
            params={"ids": f"{args['portfolio_id_a']},{args['portfolio_id_b']}"},
        )

    # ===== Category 5: Strategy Simulation (Families A-F) =====

    elif name == "analyze_kill_impact":
        return api._get(
            f"/api/simulations/family-a/kill/{args['portfolio_id']}/{args['asset_id']}"
        )

    elif name == "analyze_acceleration":
        data = {
            "budget_multiplier": args.get("budget_multiplier", 1.5),
        }
        if args.get("phase_name"):
            data["phase_name"] = args["phase_name"]
        return api._post(
            f"/api/simulations/family-a/accelerate/{args['portfolio_id']}/{args['asset_id']}",
            json_data=data,
        )

    elif name == "get_ta_budget_distribution":
        return api._get(
            f"/api/simulations/family-b/ta-efficiency/{args['portfolio_id']}"
        )

    elif name == "get_temporal_balance":
        return api._get(
            f"/api/simulations/family-c/launch-timeline/{args['portfolio_id']}"
        )

    elif name == "get_innovation_risk_charter":
        return api._get(
            f"/api/simulations/family-d/innovation-score/{args['portfolio_id']}"
        )

    elif name == "analyze_bd_deal":
        params = {}
        if args.get("deal_name"):
            params["deal_name"] = args["deal_name"]
        if args.get("deal_type"):
            params["deal_type"] = args["deal_type"]
        if args.get("upfront_payment") is not None:
            params["upfront"] = args["upfront_payment"]
        if args.get("peak_sales") is not None:
            params["peak_sales"] = args["peak_sales"]
        return api._get(
            f"/api/simulations/family-e/bd-scan/{args['portfolio_id']}",
            params=params,
        )

    elif name == "get_concentration_analysis":
        return api._get(
            f"/api/simulations/family-f/hhi/{args['portfolio_id']}"
        )

    # ===== Category 6: Simulation Run Management =====

    elif name == "save_simulation_run":
        data = {"run_name": args["run_name"]}
        if args.get("notes"):
            data["notes"] = args["notes"]
        return api._post(
            f"/api/portfolios/{args['portfolio_id']}/runs",
            json_data=data,
        )

    elif name == "list_simulation_runs":
        return api._get(
            f"/api/portfolios/{args['portfolio_id']}/runs"
        )

    elif name == "get_simulation_run_detail":
        return api._get(
            f"/api/portfolios/{args['portfolio_id']}/runs/{args['run_id']}"
        )

    elif name == "compare_simulation_runs":
        return api._get(
            "/api/portfolios/compare-runs",
            params={"run_ids": f"{args['run_id_a']},{args['run_id_b']}"},
        )

    elif name == "restore_simulation_run":
        return api._post(
            f"/api/portfolios/{args['portfolio_id']}/runs/{args['run_id']}/restore"
        )

    elif name == "label_simulation_run":
        data = {}
        if args.get("run_name"):
            data["run_name"] = args["run_name"]
        if args.get("notes"):
            data["notes"] = args["notes"]
        return api._put(
            f"/api/portfolios/{args['portfolio_id']}/runs/{args['run_id']}",
            json_data=data,
        )

    else:
        return {"error": f"Unknown tool: {name}"}


def format_tool_result_for_display(tool_name: str, result: Any) -> str:
    """
    Format a tool result into a human-readable string for display in the chat UI.
    Truncates very large results to keep the UI clean.
    """
    if isinstance(result, dict) and "error" in result:
        return f"Error: {result['error']}"

    try:
        text = json.dumps(result, indent=2, default=str)
        # Truncate very long results
        if len(text) > 3000:
            text = text[:3000] + "\n... (truncated)"
        return text
    except Exception:
        return str(result)[:3000]

