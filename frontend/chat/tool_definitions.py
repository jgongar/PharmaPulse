"""
PharmaPulse — Tool Definitions for LLM Function Calling

These are the Anthropic-format tool definitions that get passed to Claude
(or any LLM provider that supports function calling). They mirror the MCP
server tool definitions but are formatted for direct API usage.

Each tool has:
  - name: matches the tool executor dispatch table
  - description: helps the LLM decide when to use the tool
  - input_schema: JSON Schema for the tool's parameters
"""

# All tool definitions for the LLM
TOOL_DEFINITIONS = [
    # ===== Category 1: Data Queries =====
    {
        "name": "list_assets",
        "description": (
            "List and filter drug assets in the PharmaPulse database. "
            "Returns all assets by default. Use filters to narrow results. "
            "Use this when the user asks 'show me all projects' or 'list internal assets'."
        ),
        "input_schema": {
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
            },
        },
    },
    {
        "name": "get_asset_detail",
        "description": (
            "Get detailed information about a specific asset including all its snapshots. "
            "Use this when the user asks about a specific drug/project by name or ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "integer",
                    "description": "The asset ID to look up.",
                },
            },
            "required": ["asset_id"],
        },
    },
    {
        "name": "get_snapshot_detail",
        "description": (
            "Get full snapshot detail with all inputs (phases, R&D costs, commercial data, "
            "MC config) and results. Use when user asks about specific valuation assumptions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID.",
                },
            },
            "required": ["snapshot_id"],
        },
    },
    {
        "name": "get_cashflows",
        "description": (
            "Get calculated cashflow table for a snapshot. Returns year-by-year revenue, "
            "costs, tax, risk-adjusted FCF, and present values."
        ),
        "input_schema": {
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
            },
            "required": ["snapshot_id"],
        },
    },
    {
        "name": "search_assets",
        "description": (
            "Search assets by compound name, therapeutic area, phase, or NPV range. "
            "Use when the user says 'find', 'search', or 'which assets have NPV above X'."
        ),
        "input_schema": {
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
    },

    # ===== Category 2: NPV Calculations =====
    {
        "name": "run_deterministic_npv",
        "description": (
            "Run deterministic risk-adjusted NPV calculation for a snapshot. "
            "Use this when the user asks to 'calculate NPV' or 'run valuation'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID to calculate NPV for.",
                },
            },
            "required": ["snapshot_id"],
        },
    },
    {
        "name": "run_monte_carlo",
        "description": (
            "Run Monte Carlo simulation for a snapshot. Returns distribution statistics "
            "(mean, P10, P50, P90, std dev). Use for 'Monte Carlo' or 'range of outcomes'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "snapshot_id": {
                    "type": "integer",
                    "description": "The snapshot ID.",
                },
                "iterations": {
                    "type": "integer",
                    "description": "Number of MC iterations (default: 1000).",
                },
            },
            "required": ["snapshot_id"],
        },
    },

    # ===== Category 3: Portfolio Management =====
    {
        "name": "list_portfolios",
        "description": (
            "List all portfolios with project count, saved runs count, and latest run info. "
            "Use when user asks 'show my portfolios' or 'list portfolios'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_portfolio_detail",
        "description": (
            "Get full portfolio detail including projects, overrides, added projects, "
            "BD placeholders, and all saved simulation runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "The portfolio ID.",
                },
            },
            "required": ["portfolio_id"],
        },
    },
    {
        "name": "create_portfolio",
        "description": (
            "Create a new portfolio. For base portfolios, optionally include asset_ids "
            "to add all projects in one call. For scenario portfolios, base_portfolio_id required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Name for the new portfolio.",
                },
                "portfolio_type": {
                    "type": "string",
                    "enum": ["base", "scenario"],
                    "description": "Type: 'base' or 'scenario'.",
                },
                "base_portfolio_id": {
                    "type": "integer",
                    "description": "Required for scenario portfolios.",
                },
                "asset_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of asset IDs to add.",
                },
            },
            "required": ["portfolio_name", "portfolio_type"],
        },
    },
    {
        "name": "add_project_to_portfolio",
        "description": "Add a project (drug asset) to an existing portfolio.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset ID to add."},
            },
            "required": ["portfolio_id", "asset_id"],
        },
    },
    {
        "name": "remove_project_from_portfolio",
        "description": "Remove a project from a portfolio entirely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset ID to remove."},
            },
            "required": ["portfolio_id", "asset_id"],
        },
    },
    {
        "name": "cancel_project_in_portfolio",
        "description": (
            "Deactivate (kill) a project in a portfolio. Sets NPV contribution to 0 "
            "but keeps it for comparison. Only works on scenario portfolios."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset ID."},
            },
            "required": ["portfolio_id", "asset_id"],
        },
    },
    {
        "name": "reactivate_project_in_portfolio",
        "description": "Reactivate a previously cancelled project in a portfolio.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset ID."},
            },
            "required": ["portfolio_id", "asset_id"],
        },
    },

    # ===== Category 4: Portfolio Simulation =====
    {
        "name": "add_portfolio_override",
        "description": (
            "Add a scenario override to a project in a portfolio. Override types: "
            "peak_sales_change, sr_override, phase_delay, launch_delay, "
            "time_to_peak_change, accelerate, budget_realloc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "portfolio_project_id": {"type": "integer", "description": "The portfolio project ID."},
                "override_type": {
                    "type": "string",
                    "enum": [
                        "peak_sales_change", "sr_override", "phase_delay",
                        "launch_delay", "time_to_peak_change", "accelerate",
                        "budget_realloc", "project_kill", "project_add", "bd_add",
                    ],
                    "description": "Type of override.",
                },
                "override_value": {"type": "number", "description": "Override value."},
                "phase_name": {"type": "string", "description": "Phase name (for sr_override, phase_delay)."},
                "description": {"type": "string", "description": "Description of the override."},
            },
            "required": ["portfolio_id", "portfolio_project_id", "override_type", "override_value"],
        },
    },
    {
        "name": "remove_portfolio_override",
        "description": "Remove a scenario override from a portfolio project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "override_id": {"type": "integer", "description": "The override ID to remove."},
            },
            "required": ["portfolio_id", "override_id"],
        },
    },
    {
        "name": "add_hypothetical_project",
        "description": (
            "Add a hypothetical project to a portfolio for what-if analysis. "
            "Use when user says 'what if we added a project in Oncology'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "compound_name": {"type": "string", "description": "Hypothetical compound name."},
                "therapeutic_area": {"type": "string", "description": "Therapeutic area."},
                "indication": {"type": "string", "description": "Target indication."},
                "current_phase": {"type": "string", "description": "Current phase."},
                "peak_sales": {"type": "number", "description": "Peak sales (EUR mm)."},
            },
            "required": ["portfolio_id", "compound_name", "therapeutic_area", "indication", "current_phase", "peak_sales"],
        },
    },
    {
        "name": "run_portfolio_simulation",
        "description": (
            "Run portfolio simulation. Calculates NPV for all projects, applies overrides, "
            "and aggregates totals. Use after adding overrides or when user says 'simulate'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    },
    {
        "name": "compare_portfolios",
        "description": (
            "Compare two portfolios side-by-side. Returns NPV delta and percentage change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id_a": {"type": "integer", "description": "First portfolio ID."},
                "portfolio_id_b": {"type": "integer", "description": "Second portfolio ID."},
            },
            "required": ["portfolio_id_a", "portfolio_id_b"],
        },
    },

    # ===== Category 5: Strategy Simulation (Families A-F) =====
    {
        "name": "analyze_kill_impact",
        "description": (
            "Analyze the impact of killing a project: NPV lost, R&D freed, portfolio effect. "
            "Family A: Kill/Continue/Accelerate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset to analyze."},
            },
            "required": ["portfolio_id", "asset_id"],
        },
    },
    {
        "name": "analyze_acceleration",
        "description": (
            "Analyze accelerating a project: NPV gained from earlier launch vs increased R&D cost."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "asset_id": {"type": "integer", "description": "The asset to accelerate."},
                "months_acceleration": {"type": "integer", "description": "Months to accelerate by."},
                "budget_multiplier": {"type": "number", "description": "R&D budget multiplier (e.g., 1.3)."},
            },
            "required": ["portfolio_id", "asset_id", "months_acceleration"],
        },
    },
    {
        "name": "get_ta_budget_distribution",
        "description": "Get therapeutic area budget distribution for a portfolio. Family B.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    },
    {
        "name": "get_temporal_balance",
        "description": "Get temporal cashflow balance analysis (waterfall). Family C.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    },
    {
        "name": "get_innovation_risk_charter",
        "description": "Get Innovation vs Risk scatter plot data for portfolio projects. Family D.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    },
    {
        "name": "analyze_bd_deal",
        "description": (
            "Model a business development deal: upfront, milestones, royalties, revenue sharing. Family E."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "deal_name": {"type": "string", "description": "Name of the BD deal."},
                "deal_type": {"type": "string", "description": "Deal type: in-license, acquisition, co-development."},
                "upfront_payment": {"type": "number", "description": "Upfront payment (EUR mm)."},
                "peak_sales": {"type": "number", "description": "Expected peak sales (EUR mm)."},
            },
            "required": ["portfolio_id", "deal_name", "deal_type"],
        },
    },
    {
        "name": "get_concentration_analysis",
        "description": (
            "Analyze portfolio concentration risk by therapeutic area, phase, "
            "and single-asset dependency. Family F."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    },

    # ===== Category 6: Simulation Run Management =====
    {
        "name": "save_simulation_run",
        "description": (
            "Save current portfolio simulation state as a named, immutable run. "
            "Use after running a simulation when user says 'save this'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "run_name": {"type": "string", "description": "Name for the saved run."},
                "notes": {"type": "string", "description": "Optional notes."},
            },
            "required": ["portfolio_id", "run_name"],
        },
    },
    {
        "name": "list_simulation_runs",
        "description": "List all saved simulation runs for a portfolio, newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
            },
            "required": ["portfolio_id"],
        },
    },
    {
        "name": "get_simulation_run_detail",
        "description": "Get full detail of a saved simulation run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "run_id": {"type": "integer", "description": "The run ID."},
            },
            "required": ["portfolio_id", "run_id"],
        },
    },
    {
        "name": "compare_simulation_runs",
        "description": "Compare two saved simulation runs side-by-side.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id_a": {"type": "integer", "description": "First run ID."},
                "run_id_b": {"type": "integer", "description": "Second run ID."},
            },
            "required": ["run_id_a", "run_id_b"],
        },
    },
    {
        "name": "restore_simulation_run",
        "description": (
            "Restore overrides from a saved run as current working state. "
            "Use when user says 'go back to Option A'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "run_id": {"type": "integer", "description": "The run ID to restore."},
            },
            "required": ["portfolio_id", "run_id"],
        },
    },
    {
        "name": "label_simulation_run",
        "description": "Update a simulation run's name or notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_id": {"type": "integer", "description": "The portfolio ID."},
                "run_id": {"type": "integer", "description": "The run ID."},
                "run_name": {"type": "string", "description": "New name."},
                "notes": {"type": "string", "description": "New notes."},
            },
            "required": ["portfolio_id", "run_id"],
        },
    },
]

