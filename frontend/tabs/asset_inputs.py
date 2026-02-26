"""
Tab 2: Asset Inputs — View and edit all valuation inputs for a selected asset-snapshot.

Features:
- Snapshot selector with new/clone functionality
- General parameters editor
- Phase inputs editor
- R&D costs editor
- Commercial rows editor
- Action buttons for save and run NPV
"""

import streamlit as st
import pandas as pd
from frontend.api_client import api


def render():
    """Render the Asset Inputs tab."""

    if not st.session_state.get("selected_asset_id"):
        st.info("Please select an asset from the Portfolio View tab first.")
        return

    asset_id = st.session_state.selected_asset_id

    # Fetch asset details
    try:
        asset = api.get_asset(asset_id)
    except Exception as e:
        st.error(f"Error loading asset: {e}")
        return

    # Header
    st.subheader(f"{asset['compound_name']} — {asset['indication']}")
    st.caption(f"Sponsor: {asset['sponsor']} | TA: {asset['therapeutic_area']} | Phase: {asset['current_phase']}")

    # ---- Edit Asset Metadata ----
    with st.expander("✏️ Edit Asset Metadata (compound, sponsor, TA, phase…)", expanded=False):
        _render_asset_metadata_editor(asset_id, asset)

    # Snapshot selector
    try:
        snapshots = api.get_snapshots(asset_id)
    except Exception as e:
        st.error(f"Error loading snapshots: {e}")
        return

    if not snapshots:
        st.warning("No snapshots found for this asset.")
        return

    snap_options = {s["snapshot_name"]: s["id"] for s in snapshots}

    col1, col2, col3 = st.columns([4, 2, 2])
    with col1:
        selected_snap = st.selectbox(
            "Select Snapshot",
            options=list(snap_options.keys()),
            key="ai_snap_select",
        )
    with col2:
        if st.button("Clone Snapshot"):
            clone_name = f"{selected_snap} (Copy)"
            try:
                result = api.clone_snapshot(asset_id, snap_options[selected_snap], clone_name)
                st.success(f"Cloned as '{clone_name}'")
                st.rerun()
            except Exception as e:
                st.error(f"Clone failed: {e}")

    if selected_snap:
        snapshot_id = snap_options[selected_snap]
        st.session_state.selected_snapshot_id = snapshot_id

        # Load snapshot detail
        try:
            detail = api.get_snapshot_detail(snapshot_id)
        except Exception as e:
            st.error(f"Error loading snapshot detail: {e}")
            return

        snapshot = detail.get("snapshot", detail)

        # ---- Section 1: General Parameters (editable) ----
        st.markdown("### General Parameters")
        st.caption("Edit snapshot name, valuation parameters and click **Save General Parameters**.")

        col_name, col_desc = st.columns(2)
        with col_name:
            edit_snap_name = st.text_input(
                "Snapshot Name",
                value=snapshot.get("snapshot_name", ""),
                key=f"gp_snap_name_{snapshot_id}",
            )
        with col_desc:
            edit_description = st.text_input(
                "Description",
                value=snapshot.get("description", "") or "",
                key=f"gp_description_{snapshot_id}",
            )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            edit_val_year = st.number_input(
                "Valuation Year",
                min_value=2020, max_value=2050,
                value=int(snapshot.get("valuation_year", 2025)),
                key=f"gp_val_year_{snapshot_id}",
            )
        with col2:
            edit_horizon = st.number_input(
                "Horizon (years)",
                min_value=1, max_value=50,
                value=int(snapshot.get("horizon_years", 20)),
                key=f"gp_horizon_{snapshot_id}",
            )
        with col3:
            edit_wacc = st.number_input(
                "WACC R&D (%)",
                min_value=0.0, max_value=30.0, step=0.1,
                value=round((snapshot.get("wacc_rd", 0) or 0) * 100, 2),
                key=f"gp_wacc_{snapshot_id}",
            )
        with col4:
            edit_approval = st.number_input(
                "Approval Date",
                min_value=2020.0, max_value=2060.0, step=0.25,
                value=float(snapshot.get("approval_date", 2030)),
                format="%.2f",
                key=f"gp_approval_{snapshot_id}",
            )

        col5, col6, col_save = st.columns([2, 2, 2])
        with col5:
            edit_mc_iter = st.number_input(
                "MC Iterations",
                min_value=100, max_value=100000, step=100,
                value=int(snapshot.get("mc_iterations", 1000)),
                key=f"gp_mc_iter_{snapshot_id}",
            )
        with col6:
            edit_seed = st.number_input(
                "Random Seed",
                min_value=0, max_value=999999, step=1,
                value=int(snapshot.get("random_seed", 42)),
                key=f"gp_seed_{snapshot_id}",
            )
        with col_save:
            st.markdown("<br>", unsafe_allow_html=True)  # vertical spacer
            if st.button("💾 Save General Parameters", type="primary", key=f"gp_save_{snapshot_id}"):
                payload = {
                    "snapshot_name": edit_snap_name,
                    "description": edit_description or None,
                    "valuation_year": edit_val_year,
                    "horizon_years": edit_horizon,
                    "wacc_rd": round(edit_wacc / 100, 6),
                    "approval_date": edit_approval,
                    "mc_iterations": edit_mc_iter,
                    "random_seed": edit_seed,
                }
                try:
                    result = api.update_snapshot_general(snapshot_id, payload)
                    st.success(f"Saved! {result.get('detail', '')}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")

        # ---- Section 2: Phase Inputs ----
        st.markdown("### Phase Inputs")
        phases = detail.get("phase_inputs", [])
        if phases:
            df_phases = pd.DataFrame(phases)
            display_cols = ["phase_name", "start_date", "success_rate"]
            existing_cols = [c for c in display_cols if c in df_phases.columns]
            df_phases = df_phases[existing_cols].copy()
            df_phases.rename(columns={
                "phase_name": "Phase",
                "start_date": "Start Date",
                "success_rate": "Success Rate",
            }, inplace=True)
            if "Success Rate" in df_phases.columns:
                df_phases["Success Rate"] = df_phases["Success Rate"].apply(lambda x: f"{x:.0%}")
            st.dataframe(df_phases, use_container_width=True, hide_index=True)
        else:
            st.info("No phase inputs defined.")

        # ---- Section 3: R&D Costs ----
        st.markdown("### R&D Costs (EUR mm)")
        rd_costs = detail.get("rd_costs", [])
        if rd_costs:
            df_rd = pd.DataFrame(rd_costs)
            display_cols = ["year", "phase_name", "rd_cost"]
            existing_cols = [c for c in display_cols if c in df_rd.columns]
            df_rd = df_rd[existing_cols].copy()
            df_rd.rename(columns={
                "year": "Year",
                "phase_name": "Phase",
                "rd_cost": "R&D Cost (EUR mm)",
            }, inplace=True)
            st.dataframe(df_rd, use_container_width=True, hide_index=True)
        else:
            st.info("No R&D costs defined.")

        # ---- Section 4: Commercial Rows (editable) ----
        st.markdown("### Commercial Forecast")
        st.caption("Edit the table below, add rows, or delete rows. Click **Save Commercial Rows** to persist.")
        commercial = detail.get("commercial_rows", [])
        _render_commercial_editor(snapshot_id, commercial)

        # ---- Section 5: Monte Carlo Configuration ----
        st.markdown("### Monte Carlo Configuration")
        _render_mc_config(snapshot_id, detail, snapshot)

        # ---- Section 6: Results Summary ----
        st.markdown("### Current Results")
        col1, col2, col3 = st.columns(3)
        with col1:
            npv_det = snapshot.get("npv_deterministic")
            st.metric(
                "Deterministic rNPV",
                f"{npv_det:,.1f} EUR mm" if npv_det else "Not calculated",
            )
        with col2:
            npv_wi = snapshot.get("npv_deterministic_whatif")
            st.metric(
                "What-If rNPV",
                f"{npv_wi:,.1f} EUR mm" if npv_wi else "Not calculated",
            )
        with col3:
            npv_mc = snapshot.get("npv_mc_average")
            st.metric(
                "MC Average rNPV",
                f"{npv_mc:,.1f} EUR mm" if npv_mc else "Not calculated",
            )

        # ---- Action Buttons ----
        st.divider()
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Run Deterministic NPV", type="primary", use_container_width=True):
                with st.spinner("Calculating deterministic rNPV..."):
                    try:
                        result = api.run_deterministic_npv(snapshot_id)
                        st.success(
                            f"Deterministic rNPV = {result['npv_deterministic']:,.1f} EUR mm "
                            f"(POS: {result['cumulative_pos']:.1%})"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Calculation failed: {e}")

        with col2:
            if st.button("Run Monte Carlo", use_container_width=True):
                with st.spinner("Running Monte Carlo simulation..."):
                    try:
                        result = api.run_monte_carlo(snapshot_id)
                        st.success(
                            f"MC Average rNPV = {result['average_npv']:,.1f} EUR mm "
                            f"(P10: {result['percentiles']['p10']:,.1f}, P90: {result['percentiles']['p90']:,.1f})"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Monte Carlo failed: {e}")

        with col3:
            if st.button("Run What-If NPV", use_container_width=True):
                with st.spinner("Calculating what-if rNPV..."):
                    try:
                        result = api.run_deterministic_whatif(snapshot_id)
                        st.success(f"What-If rNPV = {result['npv_deterministic']:,.1f} EUR mm")
                        st.rerun()
                    except Exception as e:
                        st.error(f"What-If calculation failed: {e}")


_CORR_OPTIONS = [
    "Not included",
    "Same for all regions and scenarios",
    "Same for all scenarios within the same region",
    "Same for all regions within the same scenario",
    "Independent",
]

_RD_TOGGLE_OPTIONS = ["Not Included", "Included"]


def _render_mc_config(snapshot_id: int, detail: dict, snapshot: dict):
    """Render the full Monte Carlo configuration editor."""

    mc_comm = detail.get("mc_commercial_config") or {}
    mc_rd_list = detail.get("mc_rd_configs") or []
    # Build lookup: {(phase_name, variable): config_dict}
    mc_rd_map = {(c["phase_name"], c["variable"]): c for c in mc_rd_list}
    phases = detail.get("phase_inputs", [])

    # ---- Simulation Settings ----
    with st.expander("Simulation Settings", expanded=False):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            new_iterations = st.number_input(
                "Iterations", min_value=100, max_value=100000,
                value=int(snapshot.get("mc_iterations") or 1000),
                step=500, key="mc_iterations_input",
            )
        with col2:
            new_seed = st.number_input(
                "Random Seed", min_value=0, max_value=99999,
                value=int(snapshot.get("random_seed") or 42),
                step=1, key="mc_seed_input",
            )
        with col3:
            st.write("")
            st.write("")
            if st.button("Save", key="mc_save_settings"):
                try:
                    api.update_snapshot_settings(snapshot_id, new_iterations, new_seed)
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

    # ---- Commercial Uncertainty ----
    with st.expander("Commercial Uncertainty", expanded=True):
        st.caption(
            "Configure 3-point distributions and Bernoulli events for commercial variables. "
            "Low/High values are multipliers (e.g. 0.8 = 80% of base)."
        )

        comm_vars = [
            ("target_population", "Target Population", "Multiplier on patient population"),
            ("market_share",      "Market Share",      "Multiplier on market share"),
            ("time_to_peak",      "Time to Peak",      "Multiplier on time-to-peak years"),
            ("gross_price",       "Gross Price",       "Multiplier on gross price per treatment"),
        ]

        new_comm = {}

        for var_key, var_label, var_help in comm_vars:
            st.markdown(f"**{var_label}** — *{var_help}*")
            toggle_key = f"use_{var_key}"
            current_toggle = mc_comm.get(toggle_key, "Not included")
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
            with col1:
                toggle = st.selectbox(
                    "Correlation", _CORR_OPTIONS,
                    index=_CORR_OPTIONS.index(current_toggle) if current_toggle in _CORR_OPTIONS else 0,
                    key=f"mc_comm_{var_key}_toggle", label_visibility="collapsed",
                )
            new_comm[toggle_key] = toggle
            if toggle != "Not included":
                with col2:
                    new_comm[f"low_{var_key}"] = st.number_input(
                        "Low val", value=float(mc_comm.get(f"low_{var_key}") or 0.8),
                        step=0.05, format="%.2f", key=f"mc_comm_{var_key}_low_val",
                    )
                with col3:
                    new_comm[f"low_{var_key}_prob"] = st.number_input(
                        "Low prob", min_value=0.0, max_value=1.0,
                        value=float(mc_comm.get(f"low_{var_key}_prob") or 0.2),
                        step=0.05, format="%.2f", key=f"mc_comm_{var_key}_low_prob",
                    )
                with col4:
                    new_comm[f"high_{var_key}"] = st.number_input(
                        "High val", value=float(mc_comm.get(f"high_{var_key}") or 1.2),
                        step=0.05, format="%.2f", key=f"mc_comm_{var_key}_high_val",
                    )
                with col5:
                    new_comm[f"high_{var_key}_prob"] = st.number_input(
                        "High prob", min_value=0.0, max_value=1.0,
                        value=float(mc_comm.get(f"high_{var_key}_prob") or 0.2),
                        step=0.05, format="%.2f", key=f"mc_comm_{var_key}_high_prob",
                    )
                st.caption("↑ Low val | Low prob | High val | High prob  (Base prob = 1 - low_prob - high_prob)")
            else:
                for f in [f"low_{var_key}", f"low_{var_key}_prob", f"high_{var_key}", f"high_{var_key}_prob"]:
                    new_comm[f] = mc_comm.get(f)

        st.markdown("**Bernoulli Events**")
        st.caption("One-off shock events (e.g. price cut, market share collapse). Value is the absolute override if event fires.")

        for ev_key, ev_label in [("price_event", "Price Event"), ("market_share_event", "Market Share Event")]:
            toggle_key = f"use_{ev_key}"
            current_toggle = mc_comm.get(toggle_key, "Not included")
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                ev_options = ["Not included", "Same for all regions and scenarios",
                              "Same for all scenarios within the same region", "Independent"]
                ev_toggle = st.selectbox(
                    ev_label, ev_options,
                    index=ev_options.index(current_toggle) if current_toggle in ev_options else 0,
                    key=f"mc_comm_{ev_key}_toggle",
                )
            new_comm[toggle_key] = ev_toggle
            if ev_toggle != "Not included":
                with col2:
                    new_comm[f"{ev_key}_value"] = st.number_input(
                        "Override value", value=float(mc_comm.get(f"{ev_key}_value") or 0.0),
                        step=1000.0, key=f"mc_comm_{ev_key}_value",
                    )
                with col3:
                    new_comm[f"{ev_key}_prob"] = st.number_input(
                        "Probability", min_value=0.0, max_value=1.0,
                        value=float(mc_comm.get(f"{ev_key}_prob") or 0.1),
                        step=0.05, format="%.2f", key=f"mc_comm_{ev_key}_prob",
                    )
            else:
                new_comm[f"{ev_key}_value"] = mc_comm.get(f"{ev_key}_value")
                new_comm[f"{ev_key}_prob"] = mc_comm.get(f"{ev_key}_prob")

        if st.button("Save Commercial MC Config", type="primary", key="mc_save_comm"):
            try:
                api.update_mc_commercial_config(snapshot_id, new_comm)
                st.success("Commercial MC config saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")

    # ---- R&D Uncertainty ----
    with st.expander("R&D Uncertainty", expanded=True):
        st.caption(
            "Configure 3-point distributions for R&D variables per phase. "
            "Success Rate: absolute override (0–1). Duration: months shift. Cost: cost multiplier."
        )

        rd_variables = [
            ("success_rate", "Success Rate", "0.0–1.0 absolute override"),
            ("duration",     "Duration (months)", "months shift (positive = delay)"),
            ("cost",         "Cost Multiplier", "multiplier on R&D costs (1.0 = no change)"),
        ]

        new_rd_configs = []

        if not phases:
            st.info("No phases defined for this snapshot.")
        else:
            for phase in phases:
                phase_name = phase["phase_name"]
                st.markdown(f"**{phase_name}** (base SR: {phase['success_rate']:.0%})")

                cols = st.columns([2, 1, 1, 1, 1, 1])
                cols[0].caption("Variable")
                cols[1].caption("Toggle")
                cols[2].caption("Min value")
                cols[3].caption("Min prob")
                cols[4].caption("Max value")
                cols[5].caption("Max prob")

                for var_key, var_label, var_hint in rd_variables:
                    existing = mc_rd_map.get((phase_name, var_key), {})
                    c0, c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 1, 1])
                    with c0:
                        st.write(f"*{var_label}*")
                        st.caption(var_hint)
                    with c1:
                        current = existing.get("toggle", "Not Included")
                        toggle = st.selectbox(
                            "Toggle", _RD_TOGGLE_OPTIONS,
                            index=_RD_TOGGLE_OPTIONS.index(current) if current in _RD_TOGGLE_OPTIONS else 0,
                            key=f"mc_rd_{phase_name}_{var_key}_toggle",
                            label_visibility="collapsed",
                        )
                    if toggle == "Included":
                        with c2:
                            min_val = st.number_input(
                                "Min", value=float(existing.get("min_value") or (0.0 if var_key == "success_rate" else 0.8)),
                                step=0.05 if var_key != "duration" else 3.0,
                                format="%.2f" if var_key != "duration" else "%.0f",
                                key=f"mc_rd_{phase_name}_{var_key}_min_val",
                                label_visibility="collapsed",
                            )
                        with c3:
                            min_prob = st.number_input(
                                "Min prob", min_value=0.0, max_value=1.0,
                                value=float(existing.get("min_probability") or 0.2),
                                step=0.05, format="%.2f",
                                key=f"mc_rd_{phase_name}_{var_key}_min_prob",
                                label_visibility="collapsed",
                            )
                        with c4:
                            max_val = st.number_input(
                                "Max", value=float(existing.get("max_value") or (1.0 if var_key == "success_rate" else 1.2)),
                                step=0.05 if var_key != "duration" else 3.0,
                                format="%.2f" if var_key != "duration" else "%.0f",
                                key=f"mc_rd_{phase_name}_{var_key}_max_val",
                                label_visibility="collapsed",
                            )
                        with c5:
                            max_prob = st.number_input(
                                "Max prob", min_value=0.0, max_value=1.0,
                                value=float(existing.get("max_probability") or 0.2),
                                step=0.05, format="%.2f",
                                key=f"mc_rd_{phase_name}_{var_key}_max_prob",
                                label_visibility="collapsed",
                            )
                        new_rd_configs.append({
                            "phase_name": phase_name, "variable": var_key,
                            "toggle": "Included",
                            "min_value": min_val, "min_probability": min_prob,
                            "max_value": max_val, "max_probability": max_prob,
                        })
                    else:
                        new_rd_configs.append({
                            "phase_name": phase_name, "variable": var_key,
                            "toggle": "Not Included",
                            "min_value": None, "min_probability": None,
                            "max_value": None, "max_probability": None,
                        })

        if st.button("Save R&D MC Config", type="primary", key="mc_save_rd"):
            try:
                api.update_mc_rd_configs(snapshot_id, new_rd_configs)
                st.success(f"R&D MC config saved ({len([c for c in new_rd_configs if c['toggle'] == 'Included'])} variables active).")
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")


# ---------------------------------------------------------------------------
# Commercial Rows Editor
# ---------------------------------------------------------------------------

# All columns the backend requires for a commercial row
_COMMERCIAL_COLS = [
    "region", "scenario", "scenario_probability", "segment_name", "include_flag",
    "patient_population", "epi_f1", "epi_f2", "epi_f3", "epi_f4", "epi_f5", "epi_f6",
    "access_rate", "market_share", "units_per_treatment", "treatments_per_year",
    "compliance_rate", "gross_price_per_treatment", "gross_to_net_price_rate",
    "time_to_peak", "plateau_years", "revenue_curve_type",
    "cogs_rate", "distribution_rate", "operating_cost_rate", "tax_rate",
    "wacc_region", "loe_year", "launch_date",
    "loe_cliff_rate", "erosion_floor_pct", "years_to_erosion_floor",
    "logistic_k", "logistic_midpoint",
]

# Default values for a new blank commercial row
_COMMERCIAL_DEFAULTS = {
    "region": "US",
    "scenario": "Base",
    "scenario_probability": 1.0,
    "segment_name": "New Segment",
    "include_flag": 1,
    "patient_population": 0.0,
    "epi_f1": 1.0, "epi_f2": 1.0, "epi_f3": 1.0,
    "epi_f4": 1.0, "epi_f5": 1.0, "epi_f6": 1.0,
    "access_rate": 0.5,
    "market_share": 0.1,
    "units_per_treatment": 1.0,
    "treatments_per_year": 1.0,
    "compliance_rate": 1.0,
    "gross_price_per_treatment": 10000.0,
    "gross_to_net_price_rate": 0.7,
    "time_to_peak": 5.0,
    "plateau_years": 3.0,
    "revenue_curve_type": "logistic",
    "cogs_rate": 0.10,
    "distribution_rate": 0.05,
    "operating_cost_rate": 0.15,
    "tax_rate": 0.21,
    "wacc_region": 0.085,
    "loe_year": 2040.0,
    "launch_date": 2030.0,
    "loe_cliff_rate": 0.7,
    "erosion_floor_pct": 0.1,
    "years_to_erosion_floor": 3.0,
    "logistic_k": 5.5,
    "logistic_midpoint": 0.5,
}


def _render_commercial_editor(snapshot_id: int, commercial: list):
    """
    Render an editable data_editor for commercial rows.
    Allows adding new rows and saving the full set back to the backend.
    """
    # Build DataFrame from existing data or start empty
    if commercial:
        df = pd.DataFrame(commercial)
        # Ensure all expected columns exist (older snapshots might lack some)
        for col in _COMMERCIAL_COLS:
            if col not in df.columns:
                df[col] = _COMMERCIAL_DEFAULTS.get(col)
        df = df[_COMMERCIAL_COLS]
    else:
        df = pd.DataFrame(columns=_COMMERCIAL_COLS)

    # Use st.data_editor so the user can edit cells, add rows, delete rows
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",  # allows adding and deleting rows
        use_container_width=True,
        hide_index=True,
        key=f"comm_editor_{snapshot_id}",
        column_config={
            "region": st.column_config.SelectboxColumn(
                "Region", options=["US", "EU", "JP", "ROW"], default="US",
            ),
            "scenario": st.column_config.TextColumn("Scenario", default="Base"),
            "scenario_probability": st.column_config.NumberColumn(
                "Prob", min_value=0.0, max_value=1.0, step=0.1, format="%.2f",
            ),
            "segment_name": st.column_config.TextColumn("Segment"),
            "include_flag": st.column_config.NumberColumn("Include", min_value=0, max_value=1, step=1),
            "patient_population": st.column_config.NumberColumn("Population", min_value=0, format="%.0f"),
            "access_rate": st.column_config.NumberColumn("Access", min_value=0.0, max_value=1.0, step=0.05, format="%.2f"),
            "market_share": st.column_config.NumberColumn("Mkt Share", min_value=0.0, max_value=1.0, step=0.01, format="%.3f"),
            "gross_price_per_treatment": st.column_config.NumberColumn("Price (EUR)", min_value=0, format="%.0f"),
            "gross_to_net_price_rate": st.column_config.NumberColumn("GTN", min_value=0.0, max_value=1.0, format="%.2f"),
            "time_to_peak": st.column_config.NumberColumn("TtP (yrs)", min_value=0.1, format="%.1f"),
            "plateau_years": st.column_config.NumberColumn("Plateau", min_value=0, format="%.1f"),
            "loe_year": st.column_config.NumberColumn("LOE Year", format="%.1f"),
            "launch_date": st.column_config.NumberColumn("Launch", format="%.2f"),
            "wacc_region": st.column_config.NumberColumn("WACC", min_value=0.0, max_value=1.0, format="%.3f"),
            "tax_rate": st.column_config.NumberColumn("Tax", min_value=0.0, max_value=1.0, format="%.2f"),
            "cogs_rate": st.column_config.NumberColumn("COGS", min_value=0.0, max_value=1.0, format="%.2f"),
            "distribution_rate": st.column_config.NumberColumn("Dist.", min_value=0.0, max_value=1.0, format="%.2f"),
            "operating_cost_rate": st.column_config.NumberColumn("OpEx", min_value=0.0, max_value=1.0, format="%.2f"),
            "loe_cliff_rate": st.column_config.NumberColumn("LOE Cliff", min_value=0.0, max_value=1.0, format="%.2f"),
            "erosion_floor_pct": st.column_config.NumberColumn("Erosion Floor", min_value=0.0, max_value=1.0, format="%.2f"),
            "years_to_erosion_floor": st.column_config.NumberColumn("Yrs to Floor", min_value=0, format="%.1f"),
            "revenue_curve_type": st.column_config.SelectboxColumn(
                "Curve", options=["logistic", "linear", "scurve"], default="logistic",
            ),
            "logistic_k": st.column_config.NumberColumn("k", format="%.1f"),
            "logistic_midpoint": st.column_config.NumberColumn("Midpoint", format="%.2f"),
            "epi_f1": st.column_config.NumberColumn("epi_f1", format="%.2f"),
            "epi_f2": st.column_config.NumberColumn("epi_f2", format="%.2f"),
            "epi_f3": st.column_config.NumberColumn("epi_f3", format="%.2f"),
            "epi_f4": st.column_config.NumberColumn("epi_f4", format="%.2f"),
            "epi_f5": st.column_config.NumberColumn("epi_f5", format="%.2f"),
            "epi_f6": st.column_config.NumberColumn("epi_f6", format="%.2f"),
            "units_per_treatment": st.column_config.NumberColumn("Units/Tx", format="%.1f"),
            "treatments_per_year": st.column_config.NumberColumn("Tx/Yr", format="%.1f"),
            "compliance_rate": st.column_config.NumberColumn("Compliance", min_value=0.0, max_value=1.0, format="%.2f"),
        },
    )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("💾 Save Commercial Rows", type="primary", use_container_width=True, key="save_comm_rows"):
            _save_commercial_rows(snapshot_id, edited_df)
    with col_b:
        st.caption(f"{len(edited_df)} row(s) shown. Add rows using the **+** icon at the bottom of the table.")


def _save_commercial_rows(snapshot_id: int, df: pd.DataFrame):
    """Validate and save the edited commercial rows to the backend (full replace)."""
    if df.empty:
        st.warning("No rows to save. Add at least one commercial row.")
        return

    # Fill defaults for any NaN values (from newly added rows)
    for col in _COMMERCIAL_COLS:
        if col in df.columns and df[col].isna().any():
            df[col] = df[col].fillna(_COMMERCIAL_DEFAULTS.get(col, 0))

    rows_payload = df[_COMMERCIAL_COLS].to_dict(orient="records")

    try:
        result = api.replace_commercial_rows(snapshot_id, rows_payload)
        st.success(f"Saved {len(rows_payload)} commercial row(s).")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to save commercial rows: {e}")


# ---------------------------------------------------------------------------
# Asset Metadata Editor
# ---------------------------------------------------------------------------

_PHASE_OPTIONS_EDIT = ["Phase 1", "Phase 2", "Phase 2 B", "Phase 3", "Registration", "Approved"]
_TA_OPTIONS_EDIT = [
    "Immunology & Inflammation", "Oncology", "Neuroscience",
    "Hematology", "Rare Disease", "Vaccines", "Other",
]
_INNOVATION_OPTIONS = ["first_in_class", "best_in_class", "fast_follower", "standard"]


def _render_asset_metadata_editor(asset_id: int, asset: dict):
    """Editable form for asset-level metadata (compound, sponsor, TA, etc.)."""

    col1, col2, col3 = st.columns(3)
    with col1:
        edit_compound = st.text_input(
            "Compound Name", value=asset.get("compound_name", ""),
            key=f"am_compound_{asset_id}",
        )
    with col2:
        edit_sponsor = st.text_input(
            "Sponsor", value=asset.get("sponsor", ""),
            key=f"am_sponsor_{asset_id}",
        )
    with col3:
        current_ta = asset.get("therapeutic_area", "Other")
        ta_idx = _TA_OPTIONS_EDIT.index(current_ta) if current_ta in _TA_OPTIONS_EDIT else len(_TA_OPTIONS_EDIT) - 1
        edit_ta = st.selectbox(
            "Therapeutic Area", _TA_OPTIONS_EDIT, index=ta_idx,
            key=f"am_ta_{asset_id}",
        )

    col4, col5, col6 = st.columns(3)
    with col4:
        edit_indication = st.text_input(
            "Indication", value=asset.get("indication", ""),
            key=f"am_indication_{asset_id}",
        )
    with col5:
        current_phase = asset.get("current_phase")
        phase_idx = _PHASE_OPTIONS_EDIT.index(current_phase) if current_phase in _PHASE_OPTIONS_EDIT else 0
        edit_phase = st.selectbox(
            "Current Phase", _PHASE_OPTIONS_EDIT, index=phase_idx,
            key=f"am_phase_{asset_id}",
        )
    with col6:
        current_innov = asset.get("innovation_class", "standard")
        innov_idx = _INNOVATION_OPTIONS.index(current_innov) if current_innov in _INNOVATION_OPTIONS else 3
        edit_innov = st.selectbox(
            "Innovation Class", _INNOVATION_OPTIONS, index=innov_idx,
            key=f"am_innov_{asset_id}",
        )

    col7, col8 = st.columns(2)
    with col7:
        edit_moa = st.text_input(
            "Mechanism of Action (MoA)",
            value=asset.get("moa", "") or "",
            key=f"am_moa_{asset_id}",
        )
    with col8:
        edit_reg_complex = st.slider(
            "Regulatory Complexity",
            min_value=0.0, max_value=1.0, step=0.05,
            value=float(asset.get("regulatory_complexity", 0.5)),
            key=f"am_reg_{asset_id}",
        )

    if st.button("💾 Save Asset Metadata", type="primary", key=f"am_save_{asset_id}"):
        payload = {
            "compound_name": edit_compound,
            "sponsor": edit_sponsor,
            "therapeutic_area": edit_ta,
            "indication": edit_indication,
            "current_phase": edit_phase,
            "innovation_class": edit_innov,
            "moa": edit_moa or None,
            "regulatory_complexity": edit_reg_complex,
        }
        try:
            api.update_asset(asset_id, payload)
            st.success("Asset metadata saved!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save: {e}")
