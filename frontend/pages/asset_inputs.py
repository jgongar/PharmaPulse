"""Tab 2: Asset Inputs — EDITABLE forms for all snapshot parameters."""

import streamlit as st
import pandas as pd
import api_client


def render():
    st.header("Asset Inputs & Snapshot Editor")

    try:
        assets = api_client.list_assets()
    except Exception as e:
        st.error(f"Cannot connect to backend: {e}")
        return

    if not assets:
        st.info("No assets found.")
        return

    # Asset selector
    asset_names = {f"{a['name']} (ID:{a['id']})": a["id"] for a in assets}
    default_key = None
    if "selected_asset_id" in st.session_state:
        for k, v in asset_names.items():
            if v == st.session_state["selected_asset_id"]:
                default_key = k
                break

    selected_key = st.selectbox(
        "Select Asset", list(asset_names.keys()),
        index=list(asset_names.keys()).index(default_key) if default_key else 0,
        key="input_asset_select"
    )
    asset_id = asset_names[selected_key]
    st.session_state["selected_asset_id"] = asset_id

    # Load snapshots
    snapshots = api_client.list_snapshots(asset_id)

    col1, col2 = st.columns([3, 1])
    with col1:
        if snapshots:
            snap_labels = {f"v{s['version']}: {s['label']} (ID:{s['id']})": s["id"] for s in snapshots}
            selected_snap_key = st.selectbox("Snapshot", list(snap_labels.keys()), key="snap_select")
            snapshot_id = snap_labels[selected_snap_key]
            snap = api_client.get_snapshot(snapshot_id)
        else:
            snap = None
            st.info("No snapshots. Create one below.")
    with col2:
        if st.button("+ New Snapshot", key="new_snap_btn"):
            new_snap = api_client.create_snapshot({"asset_id": asset_id, "label": "New Snapshot"})
            st.success(f"Created snapshot v{new_snap['version']}")
            st.rerun()

    if snap is None:
        return

    st.divider()

    # ======= EDITABLE SNAPSHOT PARAMETERS =======
    st.subheader("Snapshot Parameters")

    c1, c2, c3 = st.columns(3)
    with c1:
        label = st.text_input("Label", value=snap["label"], key="snap_label")
        discount_rate = st.number_input("Discount Rate", value=snap["discount_rate"],
                                         min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="snap_dr")
        launch_year = st.number_input("Launch Year", value=snap["launch_year"],
                                       min_value=2020, max_value=2060, step=1, key="snap_ly")
    with c2:
        patent_expiry = st.number_input("Patent Expiry Year", value=snap["patent_expiry_year"],
                                         min_value=2020, max_value=2070, step=1, key="snap_pe")
        peak_sales = st.number_input("Peak Sales ($M)", value=snap["peak_sales_usd_m"],
                                      min_value=0.0, step=50.0, format="%.1f", key="snap_ps")
        time_to_peak = st.number_input("Time to Peak (years)", value=snap["time_to_peak_years"],
                                        min_value=1, max_value=20, step=1, key="snap_ttp")
    with c3:
        generic_erosion = st.number_input("Generic Erosion %", value=snap["generic_erosion_pct"],
                                           min_value=0.0, max_value=1.0, step=0.05, format="%.2f", key="snap_ge")
        cogs_pct = st.number_input("COGS %", value=snap["cogs_pct"],
                                    min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="snap_cogs")
        sga_pct = st.number_input("SG&A %", value=snap["sga_pct"],
                                   min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="snap_sga")

    c4, c5 = st.columns(2)
    with c4:
        tax_rate = st.number_input("Tax Rate", value=snap["tax_rate"],
                                    min_value=0.0, max_value=1.0, step=0.01, format="%.2f", key="snap_tax")
    with c5:
        uptake_options = ["linear", "logistic"]
        uptake_curve = st.selectbox("Uptake Curve", uptake_options,
                                     index=uptake_options.index(snap["uptake_curve"])
                                     if snap["uptake_curve"] in uptake_options else 0,
                                     key="snap_uptake")

    notes = st.text_area("Notes", value=snap.get("notes") or "", key="snap_notes")

    # ======= EDITABLE PHASE INPUTS (POS) =======
    st.divider()
    st.subheader("Phase Success Rates (POS)")
    st.caption("Edit phase probabilities, durations, and start years directly in the table below.")

    phase_data = snap.get("phase_inputs", [])
    if phase_data:
        phase_df = pd.DataFrame([{
            "Phase": p["phase_name"],
            "POS": p["probability_of_success"],
            "Duration (yr)": p["duration_years"],
            "Start Year": p["start_year"],
        } for p in phase_data])
    else:
        phase_df = pd.DataFrame({
            "Phase": ["P1", "P2", "P3", "Filing", "Approval"],
            "POS": [0.60, 0.40, 0.55, 0.90, 0.95],
            "Duration (yr)": [2.0, 3.0, 3.0, 1.0, 1.0],
            "Start Year": [2025, 2027, 2030, 2033, 2034],
        })

    edited_phases = st.data_editor(
        phase_df,
        num_rows="dynamic",
        use_container_width=True,
        key="phase_editor",
        column_config={
            "Phase": st.column_config.TextColumn("Phase"),
            "POS": st.column_config.NumberColumn("POS", min_value=0.0, max_value=1.0, step=0.01, format="%.2f"),
            "Duration (yr)": st.column_config.NumberColumn("Duration (yr)", min_value=0.5, max_value=10.0, step=0.5),
            "Start Year": st.column_config.NumberColumn("Start Year", min_value=2020, max_value=2060, step=1),
        }
    )

    # Show cumulative POS
    if not edited_phases.empty:
        cum_pos = 1.0
        for _, row in edited_phases.iterrows():
            cum_pos *= row["POS"]
        st.info(f"Cumulative POS: **{cum_pos:.2%}**")

    # ======= EDITABLE R&D COSTS =======
    st.divider()
    st.subheader("R&D Costs by Year")
    st.caption("Edit annual R&D costs. Add or remove years as needed.")

    rd_data = snap.get("rd_costs", [])
    if rd_data:
        rd_df = pd.DataFrame([{"Year": r["year"], "Cost ($M)": r["cost_usd_m"]} for r in rd_data])
    else:
        rd_df = pd.DataFrame({"Year": [2025, 2026, 2027], "Cost ($M)": [20.0, 20.0, 50.0]})

    edited_rd = st.data_editor(
        rd_df,
        num_rows="dynamic",
        use_container_width=True,
        key="rd_editor",
        column_config={
            "Year": st.column_config.NumberColumn("Year", min_value=2020, max_value=2060, step=1),
            "Cost ($M)": st.column_config.NumberColumn("Cost ($M)", min_value=0.0, step=5.0, format="%.2f"),
        }
    )

    # ======= EDITABLE COMMERCIAL CASHFLOWS =======
    st.divider()
    st.subheader("Commercial Cashflows (Optional Override)")
    st.caption("Override auto-generated commercial projections. Leave empty to use model-generated values.")

    comm_data = snap.get("commercial_rows", [])
    show_commercial = st.checkbox("Override commercial cashflows manually", value=len(comm_data) > 0 and any(
        c.get("gross_sales_usd_m", 0) > 0 for c in comm_data
    ), key="show_comm")

    edited_comm = None
    if show_commercial:
        if comm_data:
            comm_df = pd.DataFrame([{
                "Year": c["year"],
                "Gross Sales ($M)": c["gross_sales_usd_m"],
                "COGS ($M)": c["cogs_usd_m"],
                "SG&A ($M)": c["sga_usd_m"],
                "Net CF ($M)": c["net_cashflow_usd_m"],
            } for c in comm_data])
        else:
            comm_df = pd.DataFrame({
                "Year": [launch_year, launch_year + 1],
                "Gross Sales ($M)": [0.0, 0.0],
                "COGS ($M)": [0.0, 0.0],
                "SG&A ($M)": [0.0, 0.0],
                "Net CF ($M)": [0.0, 0.0],
            })

        edited_comm = st.data_editor(
            comm_df,
            num_rows="dynamic",
            use_container_width=True,
            key="comm_editor",
        )

    # ======= SAVE BUTTON =======
    st.divider()
    col_save, col_delete, col_npv = st.columns([1, 1, 1])

    with col_save:
        if st.button("Save Snapshot", type="primary", key="save_snap"):
            # Build update payload
            phase_inputs = []
            for _, row in edited_phases.iterrows():
                phase_inputs.append({
                    "phase_name": str(row["Phase"]),
                    "probability_of_success": float(row["POS"]),
                    "duration_years": float(row["Duration (yr)"]),
                    "start_year": int(row["Start Year"]),
                })

            rd_costs = []
            for _, row in edited_rd.iterrows():
                rd_costs.append({
                    "year": int(row["Year"]),
                    "cost_usd_m": float(row["Cost ($M)"]),
                })

            update_data = {
                "label": label,
                "discount_rate": discount_rate,
                "launch_year": launch_year,
                "patent_expiry_year": patent_expiry,
                "peak_sales_usd_m": peak_sales,
                "time_to_peak_years": time_to_peak,
                "generic_erosion_pct": generic_erosion,
                "cogs_pct": cogs_pct,
                "sga_pct": sga_pct,
                "tax_rate": tax_rate,
                "uptake_curve": uptake_curve,
                "notes": notes if notes else None,
                "phase_inputs": phase_inputs,
                "rd_costs": rd_costs,
            }

            if show_commercial and edited_comm is not None:
                commercial_rows = []
                for _, row in edited_comm.iterrows():
                    gross = float(row["Gross Sales ($M)"])
                    cogs_val = float(row["COGS ($M)"])
                    sga_val = float(row["SG&A ($M)"])
                    net = float(row["Net CF ($M)"])
                    commercial_rows.append({
                        "year": int(row["Year"]),
                        "gross_sales_usd_m": gross,
                        "net_sales_usd_m": gross,
                        "cogs_usd_m": cogs_val,
                        "sga_usd_m": sga_val,
                        "operating_profit_usd_m": gross - cogs_val - sga_val,
                        "tax_usd_m": 0,
                        "net_cashflow_usd_m": net,
                    })
                update_data["commercial_rows"] = commercial_rows

            try:
                api_client.update_snapshot(snap["id"], update_data)
                st.success("Snapshot saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    with col_delete:
        if st.button("Delete Snapshot", key="del_snap"):
            try:
                api_client.delete_snapshot(snap["id"])
                st.success("Deleted.")
                st.rerun()
            except Exception as e:
                st.error(f"Delete failed: {e}")

    with col_npv:
        if st.button("Run NPV", key="run_npv_btn"):
            try:
                result = api_client.run_deterministic_npv(snap["id"])
                st.session_state["last_npv_result"] = result
                st.success(f"eNPV: ${result['enpv_usd_m']:,.1f}M")
                st.session_state["active_tab"] = 3  # Go to results
                st.rerun()
            except Exception as e:
                st.error(f"NPV calculation failed: {e}")
