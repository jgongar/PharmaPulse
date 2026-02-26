"""
Tab 5: Portfolio Manager — Create, view, and manage portfolios of projects.

Features:
- List all portfolios (base + scenario)
- Create new base/scenario portfolios with bulk asset selection
- Portfolio workspace with project list
- Add/remove projects to portfolio
- Run portfolio simulation with per-project results
- Apply and manage scenario overrides
- Simulation run historization (save/restore/compare)
- Portfolio comparison
"""

import streamlit as st
import pandas as pd
import json
from frontend.api_client import api

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


def render():
    """Render the Portfolio Manager tab."""

    st.subheader("Portfolio Manager")

    # ---- Section 1: Portfolio List ----
    try:
        portfolios = api.get_portfolios()
    except Exception as e:
        st.error(f"Cannot connect to backend API: {e}")
        st.info("Make sure the backend is running on port 8050.")
        portfolios = []

    if portfolios:
        st.markdown("### All Portfolios")
        df_port = pd.DataFrame(portfolios)
        display_cols = {
            "id": "ID",
            "portfolio_name": "Name",
            "portfolio_type": "Type",
            "project_count": "Projects",
            "total_npv": "Total rNPV (EUR mm)",
            "saved_runs_count": "Saved Runs",
            "created_at": "Created",
        }

        existing_cols = [c for c in display_cols.keys() if c in df_port.columns]
        df_display = df_port[existing_cols].copy()
        df_display.rename(columns=display_cols, inplace=True)

        if "Total rNPV (EUR mm)" in df_display.columns:
            df_display["Total rNPV (EUR mm)"] = df_display["Total rNPV (EUR mm)"].apply(
                lambda x: f"{x:,.1f}" if pd.notna(x) and x is not None else "Not simulated"
            )

        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("No portfolios created yet. Create your first portfolio below.")

    st.divider()

    # ---- Section 2: Create Portfolio ----
    with st.expander("Create New Portfolio", expanded=not bool(portfolios)):
        _render_create_portfolio(portfolios)

    st.divider()

    # ---- Section 3: Portfolio Workspace ----
    if portfolios:
        st.markdown("### Portfolio Workspace")

        port_options = {
            f"{p['portfolio_name']} ({p['portfolio_type']})": p["id"]
            for p in portfolios
        }
        selected_port = st.selectbox(
            "Select Portfolio to Manage",
            options=list(port_options.keys()),
            key="pm_workspace_select",
        )

        if selected_port:
            portfolio_id = port_options[selected_port]
            _render_portfolio_workspace(portfolio_id, portfolios)


def _render_create_portfolio(portfolios: list):
    """Render the create portfolio form."""

    col1, col2 = st.columns(2)
    with col1:
        new_name = st.text_input(
            "Portfolio Name", key="pm_new_name",
            placeholder="e.g., Base Portfolio 2026",
        )
    with col2:
        port_type = st.selectbox("Type", ["base", "scenario"], key="pm_new_type")

    # If scenario, select base portfolio
    base_id = None
    if port_type == "scenario" and portfolios:
        base_options = {
            p["portfolio_name"]: p["id"]
            for p in portfolios
            if p.get("portfolio_type") == "base"
        }
        if base_options:
            selected_base = st.selectbox(
                "Base Portfolio",
                options=list(base_options.keys()),
                key="pm_base_select",
            )
            base_id = base_options[selected_base]
        else:
            st.warning("Create a base portfolio first before creating scenarios.")

    # Bulk asset selection
    st.markdown("**Select assets to include:**")
    try:
        all_assets = api.get_assets()
        internal_assets = [a for a in all_assets if a.get("is_internal")]
    except Exception:
        internal_assets = []

    if internal_assets:
        asset_options = {
            f"{a['compound_name']} - {a['indication']} ({a.get('current_phase', 'N/A')})": a["id"]
            for a in internal_assets
        }
        selected_assets = st.multiselect(
            "Assets",
            options=list(asset_options.keys()),
            default=list(asset_options.keys()),  # Select all by default
            key="pm_bulk_assets",
        )
        selected_asset_ids = [asset_options[name] for name in selected_assets]
    else:
        selected_asset_ids = []
        st.info("No internal assets available to add.")

    if st.button("Create Portfolio", type="primary", key="pm_create_btn"):
        if not new_name:
            st.warning("Please enter a portfolio name.")
        else:
            try:
                data = {
                    "portfolio_name": new_name,
                    "portfolio_type": port_type,
                }
                if base_id:
                    data["base_portfolio_id"] = base_id
                if selected_asset_ids:
                    data["asset_ids"] = selected_asset_ids

                result = api.create_portfolio(data)
                proj_count = result.get("project_count", 0)
                st.success(
                    f"Portfolio '{new_name}' created (ID: {result.get('id', '?')}) "
                    f"with {proj_count} projects!"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create portfolio: {e}")


def _render_portfolio_workspace(portfolio_id: int, all_portfolios: list):
    """Render the full portfolio workspace for a selected portfolio."""

    try:
        port_detail = api.get_portfolio(portfolio_id)
    except Exception as e:
        st.error(f"Error loading portfolio: {e}")
        return

    # --- Portfolio Info Bar ---
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Type", port_detail.get("portfolio_type", "---").title())
    with col2:
        projects = port_detail.get("projects", [])
        active_count = sum(1 for p in projects if p.get("is_active", True))
        st.metric("Active Projects", f"{active_count}/{len(projects)}")
    with col3:
        total_npv = port_detail.get("total_npv")
        st.metric(
            "Total rNPV",
            f"{total_npv:,.1f} EUR mm" if total_npv is not None else "Not simulated",
        )
    with col4:
        saved_runs = port_detail.get("saved_runs", [])
        st.metric("Saved Runs", len(saved_runs))

    # --- Sub-tabs for workspace ---
    ws_tab1, ws_tab2, ws_tab3, ws_tab4 = st.tabs([
        "Projects",
        "Overrides",
        "Simulation",
        "Saved Runs",
    ])

    with ws_tab1:
        _render_projects_section(portfolio_id, port_detail)

    with ws_tab2:
        _render_overrides_section(portfolio_id, port_detail)

    with ws_tab3:
        _render_simulation_section(portfolio_id, port_detail)

    with ws_tab4:
        _render_saved_runs_section(portfolio_id, port_detail)


def _render_projects_section(portfolio_id: int, port_detail: dict):
    """Render the projects management section."""

    projects = port_detail.get("projects", [])

    if projects:
        st.markdown("#### Projects in Portfolio")

        # Build display table
        rows = []
        for p in projects:
            npv_display = "---"
            if p.get("npv_simulated") is not None:
                npv_display = f"{p['npv_simulated']:,.1f}"
            elif p.get("npv_original") is not None:
                npv_display = f"{p['npv_original']:,.1f}"

            rows.append({
                "Asset ID": p.get("asset_id"),
                "Compound": p.get("compound_name", "---"),
                "Active": "Yes" if p.get("is_active", True) else "KILLED",
                "Snapshot": p.get("snapshot_id"),
                "NPV Original": f"{p.get('npv_original', 0):,.1f}" if p.get("npv_original") else "---",
                "NPV Simulated": npv_display,
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Quick actions
        col1, col2 = st.columns(2)
        with col1:
            # Kill/reactivate project
            proj_names = {
                f"{p['compound_name']} (ID:{p['asset_id']})": p["asset_id"]
                for p in projects
            }
            selected_proj = st.selectbox(
                "Select project for action:",
                options=list(proj_names.keys()),
                key="pm_proj_action_select",
            )

        with col2:
            if selected_proj:
                asset_id = proj_names[selected_proj]
                proj_info = next(
                    (p for p in projects if p["asset_id"] == asset_id), None
                )
                if proj_info:
                    if proj_info.get("is_active", True):
                        if st.button("Deactivate Project", key="pm_deactivate"):
                            try:
                                api._put(
                                    f"/api/portfolios/{portfolio_id}/projects/{asset_id}/deactivate"
                                )
                                st.success(f"Project {asset_id} deactivated.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")
                    else:
                        if st.button("Reactivate Project", key="pm_reactivate"):
                            try:
                                api._put(
                                    f"/api/portfolios/{portfolio_id}/projects/{asset_id}/activate"
                                )
                                st.success(f"Project {asset_id} reactivated.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed: {e}")
    else:
        st.info("No projects in this portfolio yet.")

    # Add project form
    st.markdown("#### Add Project")
    try:
        all_assets = api.get_assets()
        existing_asset_ids = {p["asset_id"] for p in projects}
        available_assets = [
            a for a in all_assets
            if a["id"] not in existing_asset_ids and a.get("is_internal")
        ]
    except Exception:
        available_assets = []

    if available_assets:
        add_options = {
            f"{a['compound_name']} - {a['indication']}": a["id"]
            for a in available_assets
        }
        selected_add = st.selectbox(
            "Asset to add:", options=list(add_options.keys()),
            key="pm_add_project_select",
        )
        if st.button("Add to Portfolio", key="pm_add_project_btn"):
            try:
                result = api._post(
                    f"/api/portfolios/{portfolio_id}/projects",
                    json_data={"asset_id": add_options[selected_add]},
                )
                st.success(f"Project added! (ID: {result.get('portfolio_project_id')})")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to add project: {e}")
    else:
        st.caption("All internal assets are already in this portfolio.")


def _render_overrides_section(portfolio_id: int, port_detail: dict):
    """Render the overrides management section."""

    overrides = port_detail.get("overrides", [])
    projects = port_detail.get("projects", [])

    st.markdown("#### Active Overrides")
    if overrides:
        df_ov = pd.DataFrame(overrides)
        display_cols = ["compound_name", "override_type", "override_value", "phase_name", "description"]
        existing = [c for c in display_cols if c in df_ov.columns]
        st.dataframe(
            df_ov[existing].rename(columns={
                "compound_name": "Compound",
                "override_type": "Type",
                "override_value": "Value",
                "phase_name": "Phase",
                "description": "Description",
            }),
            use_container_width=True,
            hide_index=True,
        )

        # Delete override
        if overrides:
            ov_options = {
                f"#{ov['override_id']}: {ov['compound_name']} - {ov['override_type']} = {ov['override_value']}": ov["override_id"]
                for ov in overrides
            }
            selected_ov = st.selectbox(
                "Select override to remove:",
                options=list(ov_options.keys()),
                key="pm_remove_ov_select",
            )
            if st.button("Remove Override", key="pm_remove_ov_btn"):
                try:
                    api._delete(f"/api/portfolios/{portfolio_id}/overrides/{ov_options[selected_ov]}")
                    st.success("Override removed.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")
    else:
        st.info("No overrides applied yet.")

    # Add override form
    if port_detail.get("portfolio_type") == "scenario":
        st.markdown("#### Add New Override")

        if not projects:
            st.warning("Add projects to the portfolio first.")
            return

        _OVERRIDE_HELP = {
            "peak_sales_change": "% change on peak sales (e.g. 10 = +10%, -20 = -20%)",
            "sr_override":       "Absolute success rate for the selected phase (0.0–1.0, e.g. 0.6 = 60%)",
            "phase_delay":       "Months of delay added to the selected phase (e.g. 6 = +6 months)",
            "launch_delay":      "Months of delay added to commercial launch (e.g. 12 = +1 year)",
            "time_to_peak_change": "Change in time-to-peak in years (e.g. 1 = +1 year, -1 = -1 year)",
            "accelerate":        "Timeline reduction in months for the selected phase (e.g. 6 = 6 months faster)",
            "budget_realloc":    "Budget multiplier for the selected phase (e.g. 1.2 = +20% R&D cost)",
        }

        col1, col2 = st.columns(2)
        with col1:
            # Map compound name → portfolio_project_id (NOT asset_id)
            proj_for_override = {
                f"{p['compound_name']}": p["portfolio_project_id"]
                for p in projects
                if p.get("portfolio_project_id") is not None
            }
            sel_proj = st.selectbox(
                "Target project:", options=list(proj_for_override.keys()),
                key="pm_ov_proj",
            )
        with col2:
            ov_type_options = list(_OVERRIDE_HELP.keys())
            override_type = st.selectbox(
                "Override type:", ov_type_options, key="pm_ov_type",
            )

        # Show help for selected type
        if override_type in _OVERRIDE_HELP:
            st.caption(f"ℹ️ **{override_type}**: {_OVERRIDE_HELP[override_type]}")

        col3, col4 = st.columns(2)
        with col3:
            override_value = st.number_input(
                "Value:", value=0.0, step=1.0, key="pm_ov_value",
            )
        with col4:
            needs_phase = override_type in ("sr_override", "phase_delay", "accelerate", "budget_realloc")
            phase_name = st.selectbox(
                "Phase (required for phase-level overrides):",
                [None, "Phase 1", "Phase 2", "Phase 2 B", "Phase 3", "Registration"],
                key="pm_ov_phase",
                disabled=not needs_phase,
            )

        ov_desc = st.text_input("Description (optional):", key="pm_ov_desc")

        if st.button("Add Override", type="primary", key="pm_add_ov_btn"):
            if needs_phase and phase_name is None:
                st.warning(f"Override type '{override_type}' requires a phase to be selected.")
            elif not sel_proj:
                st.warning("Select a project first.")
            else:
                try:
                    pp_id = proj_for_override[sel_proj]
                    result = api._post(
                        f"/api/portfolios/{portfolio_id}/overrides",
                        json_data={
                            "portfolio_project_id": pp_id,
                            "override_type": override_type,
                            "override_value": override_value,
                            "phase_name": phase_name,
                            "description": ov_desc or None,
                        },
                    )
                    st.success(f"Override added (ID: {result.get('override_id')})")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add override: {e}")
    elif port_detail.get("portfolio_type") == "base":
        st.info("Overrides can only be added to **scenario** portfolios. Create a scenario portfolio first.")


def _render_simulation_section(portfolio_id: int, port_detail: dict):
    """Render the simulation section with results and charts."""

    st.markdown("#### Run Portfolio Simulation")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Run Simulation", type="primary", use_container_width=True):
            with st.spinner("Simulating portfolio... Computing NPV for all projects..."):
                try:
                    result = api.simulate_portfolio(portfolio_id)
                    st.success(
                        f"Simulation complete! Total rNPV = "
                        f"{result.get('total_npv', 0):,.1f} EUR mm "
                        f"({result.get('active_projects', 0)} active / "
                        f"{result.get('project_count', 0)} total projects)"
                    )
                    st.session_state["last_sim_result"] = result
                    st.rerun()
                except Exception as e:
                    st.error(f"Simulation failed: {e}")

    with col2:
        total_npv = port_detail.get("total_npv")
        st.metric(
            "Current Total rNPV",
            f"{total_npv:,.1f} EUR mm" if total_npv is not None else "---",
        )

    with col3:
        projects = port_detail.get("projects", [])
        active = sum(1 for p in projects if p.get("is_active", True))
        st.metric("Active/Total", f"{active}/{len(projects)}")

    # Show per-project results if available
    projects = port_detail.get("projects", [])
    sim_projects = [p for p in projects if p.get("npv_simulated") is not None]

    if sim_projects:
        st.markdown("#### Per-Project Results")

        rows = []
        for p in sim_projects:
            npv_orig = p.get("npv_original", 0) or 0
            npv_sim = p.get("npv_simulated", 0) or 0
            delta = npv_sim - npv_orig
            rows.append({
                "Compound": p.get("compound_name", "---"),
                "Active": "Yes" if p.get("is_active", True) else "KILLED",
                "NPV Original": f"{npv_orig:,.1f}",
                "NPV Simulated": f"{npv_sim:,.1f}",
                "Delta": f"{delta:+,.1f}",
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Chart
        if HAS_PLOTLY and len(sim_projects) > 1:
            fig = go.Figure()

            compounds = [p.get("compound_name", "?") for p in sim_projects]
            npv_orig_vals = [p.get("npv_original", 0) or 0 for p in sim_projects]
            npv_sim_vals = [p.get("npv_simulated", 0) or 0 for p in sim_projects]

            fig.add_trace(go.Bar(
                name="Original NPV",
                x=compounds,
                y=npv_orig_vals,
                marker_color="#3B82F6",
            ))
            fig.add_trace(go.Bar(
                name="Simulated NPV",
                x=compounds,
                y=npv_sim_vals,
                marker_color="#10B981",
            ))

            fig.update_layout(
                title="Project NPV: Original vs Simulated",
                xaxis_title="",
                yaxis_title="NPV (EUR mm)",
                barmode="group",
                template="plotly_white",
                height=400,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)

    # Total R&D cost and sales charts
    total_rd = port_detail.get("total_rd_cost_json")
    total_sales = port_detail.get("total_sales_json")

    if HAS_PLOTLY and (total_rd or total_sales):
        st.markdown("#### Portfolio Cashflow Overview")

        col1, col2 = st.columns(2)

        with col1:
            if total_rd:
                try:
                    rd_data = json.loads(total_rd)
                    years = sorted(rd_data.keys(), key=int)
                    values = [rd_data[y] for y in years]

                    fig_rd = go.Figure()
                    fig_rd.add_trace(go.Bar(
                        x=[int(y) for y in years],
                        y=values,
                        marker_color="#EF4444",
                        name="R&D Costs",
                    ))
                    fig_rd.update_layout(
                        title="Total R&D Cost by Year",
                        xaxis_title="Year",
                        yaxis_title="EUR mm",
                        template="plotly_white",
                        height=350,
                    )
                    st.plotly_chart(fig_rd, use_container_width=True)
                except Exception:
                    pass

        with col2:
            if total_sales:
                try:
                    sales_data = json.loads(total_sales)
                    years = sorted(sales_data.keys(), key=int)
                    values = [sales_data[y] for y in years]

                    fig_sales = go.Figure()
                    fig_sales.add_trace(go.Bar(
                        x=[int(y) for y in years],
                        y=values,
                        marker_color="#10B981",
                        name="Revenue",
                    ))
                    fig_sales.update_layout(
                        title="Total Revenue by Year",
                        xaxis_title="Year",
                        yaxis_title="EUR mm",
                        template="plotly_white",
                        height=350,
                    )
                    st.plotly_chart(fig_sales, use_container_width=True)
                except Exception:
                    pass


def _render_saved_runs_section(portfolio_id: int, port_detail: dict):
    """Render the saved simulation runs section."""

    saved_runs = port_detail.get("saved_runs", [])

    st.markdown("#### Simulation Run History")

    # Save current simulation as a run
    st.markdown("**Save Current Simulation**")
    col1, col2 = st.columns([3, 1])
    with col1:
        run_name = st.text_input(
            "Run Name:", key="pm_run_name",
            placeholder="e.g., Baseline Q1 2026",
        )
    with col2:
        run_notes = st.text_input("Notes:", key="pm_run_notes", placeholder="Optional notes")

    if st.button("Save Run", type="primary", key="pm_save_run_btn"):
        if not run_name:
            st.warning("Please enter a run name.")
        else:
            try:
                result = api._post(
                    f"/api/portfolios/{portfolio_id}/runs",
                    json_data={"run_name": run_name, "notes": run_notes or None},
                )
                st.success(
                    f"Run '{run_name}' saved! "
                    f"(ID: {result.get('run_id')}, NPV: {result.get('total_npv', 0):,.1f})"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save run: {e}")

    st.divider()

    # List saved runs
    if saved_runs:
        st.markdown("**Saved Runs**")

        df_runs = pd.DataFrame(saved_runs)
        display_cols = {
            "run_id": "ID",
            "run_name": "Name",
            "total_npv": "Total rNPV (EUR mm)",
            "run_timestamp": "Timestamp",
            "notes": "Notes",
            "overrides_count": "Overrides",
        }
        existing = [c for c in display_cols.keys() if c in df_runs.columns]
        df_display = df_runs[existing].copy()
        df_display.rename(columns=display_cols, inplace=True)

        if "Total rNPV (EUR mm)" in df_display.columns:
            df_display["Total rNPV (EUR mm)"] = df_display["Total rNPV (EUR mm)"].apply(
                lambda x: f"{x:,.1f}" if x is not None else "---"
            )

        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Run actions
        run_options = {
            f"{r['run_name']} (NPV: {r.get('total_npv', 0):,.1f})": r["run_id"]
            for r in saved_runs
        }

        col1, col2, col3 = st.columns(3)
        with col1:
            selected_run = st.selectbox(
                "Select run:", options=list(run_options.keys()),
                key="pm_run_select",
            )

        with col2:
            if st.button("Restore Run", key="pm_restore_run"):
                if selected_run:
                    try:
                        run_id = run_options[selected_run]
                        result = api._post(
                            f"/api/portfolios/{portfolio_id}/runs/{run_id}/restore"
                        )
                        st.success(
                            f"Run restored! "
                            f"Overrides: {result.get('restored_overrides_count', result.get('overrides_count', 0))}"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to restore: {e}")

        with col3:
            if st.button("Delete Run", key="pm_delete_run"):
                if selected_run:
                    try:
                        run_id = run_options[selected_run]
                        api._delete(f"/api/portfolios/{portfolio_id}/runs/{run_id}")
                        st.success("Run deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

        # Compare runs
        if len(saved_runs) >= 2:
            st.markdown("**Compare Runs**")
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                run_a = st.selectbox(
                    "Run A:", options=list(run_options.keys()),
                    key="pm_compare_a",
                )
            with col2:
                run_b_options = [k for k in run_options.keys() if k != run_a]
                run_b = st.selectbox(
                    "Run B:", options=run_b_options,
                    key="pm_compare_b",
                )
            with col3:
                if st.button("Compare", key="pm_compare_btn"):
                    try:
                        id_a = run_options[run_a]
                        id_b = run_options[run_b]
                        comparison = api._get(
                            f"/api/portfolios/compare-runs",
                            params={"run_ids": f"{id_a},{id_b}"},
                        )

                        # Display comparison
                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.metric(
                                comparison["run_a"]["run_name"],
                                f"{comparison['run_a']['total_npv']:,.1f}",
                            )
                        with c2:
                            st.metric(
                                comparison["run_b"]["run_name"],
                                f"{comparison['run_b']['total_npv']:,.1f}",
                            )
                        with c3:
                            st.metric(
                                "Delta",
                                f"{comparison['delta']['npv_delta']:+,.1f}",
                                delta=f"{comparison['delta']['npv_delta_pct']:+.1f}%",
                            )

                        # Per-asset comparison table
                        if comparison.get("per_asset_comparison"):
                            st.markdown("**Per-Asset Comparison**")
                            df_cmp = pd.DataFrame(comparison["per_asset_comparison"])
                            df_cmp.rename(columns={
                                "compound_name": "Compound",
                                "npv_run_a": f"NPV {comparison['run_a']['run_name']}",
                                "npv_run_b": f"NPV {comparison['run_b']['run_name']}",
                                "delta": "Delta",
                            }, inplace=True)
                            st.dataframe(df_cmp, use_container_width=True, hide_index=True)

                    except Exception as e:
                        st.error(f"Comparison failed: {e}")
    else:
        st.info(
            "No saved runs yet. Run a simulation first, then save it here "
            "to create an immutable snapshot for audit trail and comparison."
        )

    # Delete portfolio
    st.divider()
    st.markdown("#### Danger Zone")
    if st.button("Delete This Portfolio", key="pm_delete_portfolio"):
        try:
            api._delete(f"/api/portfolios/{portfolio_id}")
            st.success("Portfolio deleted.")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to delete: {e}")
