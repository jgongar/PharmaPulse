"""Tab 1: Portfolio Overview — shows all assets with key metrics."""

import streamlit as st
import pandas as pd
import api_client
from components import portfolio_bubble_chart


def render():
    st.header("Portfolio Overview")

    try:
        assets = api_client.list_assets()
    except Exception as e:
        st.error(f"Cannot connect to backend: {e}")
        st.info("Make sure the backend is running: `cd pharmapulse/backend && uvicorn main:app --reload --port 8000`")
        return

    if not assets:
        st.info("No assets found. Add assets to get started.")
        return

    # Build summary table
    rows = []
    for asset in assets:
        snapshots = api_client.list_snapshots(asset["id"])
        latest = snapshots[-1] if snapshots else None

        enpv = None
        cum_pos = None
        if latest and latest.get("cashflows"):
            cfs = latest["cashflows"]
            enpv = cfs[-1]["cumulative_npv_usd_m"] if cfs else None
            # Get total POS from phase inputs
            cum_pos = 1.0
            for pi in latest.get("phase_inputs", []):
                cum_pos *= pi["probability_of_success"]

        rows.append({
            "ID": asset["id"],
            "Name": asset["name"],
            "TA": asset["therapeutic_area"],
            "Indication": asset["indication"],
            "Phase": asset["current_phase"],
            "Type": "Internal" if asset["is_internal"] else "Licensed",
            "Peak Sales ($M)": latest["peak_sales_usd_m"] if latest else "-",
            "Launch Year": latest["launch_year"] if latest else "-",
            "eNPV ($M)": f"${enpv:,.1f}" if enpv is not None else "Not calculated",
            "cPOS": f"{cum_pos:.1%}" if cum_pos is not None else "-",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Bubble chart for assets with NPV data
    bubble_data = []
    for asset in assets:
        snapshots = api_client.list_snapshots(asset["id"])
        latest = snapshots[-1] if snapshots else None
        if latest and latest.get("cashflows"):
            cfs = latest["cashflows"]
            enpv = cfs[-1]["cumulative_npv_usd_m"] if cfs else 0
            cum_pos = 1.0
            for pi in latest.get("phase_inputs", []):
                cum_pos *= pi["probability_of_success"]
            bubble_data.append({
                "name": asset["name"],
                "therapeutic_area": asset["therapeutic_area"],
                "enpv_usd_m": enpv,
                "cumulative_pos": cum_pos,
                "peak_sales_usd_m": latest["peak_sales_usd_m"],
            })

    if bubble_data:
        st.plotly_chart(portfolio_bubble_chart(bubble_data), use_container_width=True)

    # Asset selector for navigation
    st.divider()
    st.subheader("Select Asset to View Details")
    asset_names = {a["name"]: a["id"] for a in assets}
    selected = st.selectbox("Asset", list(asset_names.keys()), key="portfolio_asset_select")
    if st.button("Go to Asset Inputs"):
        st.session_state["selected_asset_id"] = asset_names[selected]
        st.session_state["active_tab"] = 1
        st.rerun()
