"""Tab 4: Asset NPV Results — detailed cashflow view and comparisons."""

import streamlit as st
import pandas as pd
import api_client
from components import cashflow_chart


def render():
    st.header("NPV Results & Cashflow Detail")

    if "selected_asset_id" not in st.session_state:
        st.info("Select an asset from the Portfolio tab first.")
        return

    asset_id = st.session_state["selected_asset_id"]

    try:
        asset = api_client.get_asset(asset_id)
        snapshots = api_client.list_snapshots(asset_id)
    except Exception as e:
        st.error(f"Backend error: {e}")
        return

    st.subheader(f"{asset['name']} — {asset['therapeutic_area']} / {asset['indication']}")

    if not snapshots:
        st.info("No snapshots.")
        return

    # Snapshot selector
    snap_labels = {f"v{s['version']}: {s['label']}": s["id"] for s in snapshots}
    selected = st.selectbox("Snapshot", list(snap_labels.keys()), key="result_snap_select")
    snap_id = snap_labels[selected]
    snap = api_client.get_snapshot(snap_id)

    # Run NPV if no cashflows
    if not snap.get("cashflows"):
        if st.button("Calculate NPV", type="primary"):
            try:
                result = api_client.run_deterministic_npv(snap_id)
                st.rerun()
            except Exception as e:
                st.error(f"NPV failed: {e}")
        return

    # Summary metrics
    cashflows = snap["cashflows"]
    enpv = cashflows[-1]["cumulative_npv_usd_m"] if cashflows else 0
    cum_pos = 1.0
    for pi in snap.get("phase_inputs", []):
        cum_pos *= pi["probability_of_success"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("eNPV", f"${enpv:,.1f}M")
    c2.metric("cPOS", f"{cum_pos:.2%}")
    c3.metric("Peak Sales", f"${snap['peak_sales_usd_m']:,.0f}M")
    c4.metric("Launch Year", str(snap["launch_year"]))

    # Cashflow chart
    st.plotly_chart(cashflow_chart(cashflows), use_container_width=True)

    # Detailed cashflow table
    st.subheader("Cashflow Detail")
    cf_df = pd.DataFrame(cashflows)
    display_cols = ["year", "rd_cost_usd_m", "commercial_cf_usd_m", "net_cashflow_usd_m",
                    "cumulative_pos", "risk_adjusted_cf_usd_m", "discount_factor", "pv_usd_m", "cumulative_npv_usd_m"]
    cf_display = cf_df[[c for c in display_cols if c in cf_df.columns]].copy()
    cf_display.columns = ["Year", "R&D ($M)", "Commercial ($M)", "Net CF ($M)",
                          "Cum POS", "Risk-Adj ($M)", "DF", "PV ($M)", "Cum NPV ($M)"]

    st.dataframe(
        cf_display.style.format({
            "R&D ($M)": "${:,.1f}", "Commercial ($M)": "${:,.1f}",
            "Net CF ($M)": "${:,.1f}", "Cum POS": "{:.2%}",
            "Risk-Adj ($M)": "${:,.1f}", "DF": "{:.4f}",
            "PV ($M)": "${:,.1f}", "Cum NPV ($M)": "${:,.1f}",
        }),
        use_container_width=True, hide_index=True
    )

    # Commercial detail
    if snap.get("commercial_rows"):
        st.subheader("Commercial Projections")
        comm_df = pd.DataFrame(snap["commercial_rows"])
        display_comm = comm_df[["year", "gross_sales_usd_m", "cogs_usd_m", "sga_usd_m",
                                "operating_profit_usd_m", "tax_usd_m", "net_cashflow_usd_m"]].copy()
        display_comm.columns = ["Year", "Gross Sales ($M)", "COGS ($M)", "SG&A ($M)",
                                "Op Profit ($M)", "Tax ($M)", "Net CF ($M)"]
        st.dataframe(
            display_comm.style.format({
                "Gross Sales ($M)": "${:,.1f}", "COGS ($M)": "${:,.1f}",
                "SG&A ($M)": "${:,.1f}", "Op Profit ($M)": "${:,.1f}",
                "Tax ($M)": "${:,.1f}", "Net CF ($M)": "${:,.1f}",
            }),
            use_container_width=True, hide_index=True
        )

    # Snapshot comparison
    st.divider()
    st.subheader("Snapshot Comparison")

    if len(snapshots) >= 2:
        compare_options = [k for k in snap_labels.keys() if snap_labels[k] != snap_id]
        if compare_options:
            compare_key = st.selectbox("Compare with", compare_options, key="compare_snap")
            compare_id = snap_labels[compare_key]
            compare_snap = api_client.get_snapshot(compare_id)

            if not compare_snap.get("cashflows"):
                if st.button("Calculate NPV for comparison snapshot"):
                    api_client.run_deterministic_npv(compare_id)
                    st.rerun()
            else:
                compare_cfs = compare_snap["cashflows"]
                compare_enpv = compare_cfs[-1]["cumulative_npv_usd_m"] if compare_cfs else 0
                delta = enpv - compare_enpv

                cc1, cc2 = st.columns(2)
                cc1.metric(f"Current: {selected}", f"${enpv:,.1f}M")
                cc2.metric(f"Compare: {compare_key}", f"${compare_enpv:,.1f}M",
                           delta=f"${delta:+,.1f}M")
    else:
        st.info("Create additional snapshots to enable comparison.")

    # Export button
    st.divider()
    export_url = api_client.get_export_url(snap_id)
    st.markdown(f"[Download Excel Export]({export_url})")
