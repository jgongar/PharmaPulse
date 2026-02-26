"""
Tab 4: Results & Charts — Display all calculation results, charts, and cashflow tables.

Features:
- Key metric cards (Deterministic, What-If, MC percentiles)
- NPV by region-scenario table
- Cashflow table (yearly breakdown)
- Interactive Plotly charts: waterfall, MC distribution, revenue curve, NPV bridge
"""

import streamlit as st
import pandas as pd
import json
from frontend.api_client import api

try:
    import plotly.graph_objects as go
    import plotly.express as px
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False


def render():
    """Render the Results & Charts tab."""

    if not st.session_state.get("selected_snapshot_id"):
        st.info("Please select an asset and snapshot from the previous tabs first.")
        return

    snapshot_id = st.session_state.selected_snapshot_id

    # Load snapshot detail
    try:
        detail = api.get_snapshot_detail(snapshot_id)
    except Exception as e:
        st.error(f"Error loading snapshot: {e}")
        return

    snapshot = detail.get("snapshot", detail)

    # Try to get asset name
    try:
        asset = api.get_asset(snapshot.get("asset_id"))
        asset_name = f"{asset['compound_name']} — {asset['indication']}"
    except Exception:
        asset_name = "Selected Asset"

    st.subheader(f"Results — {snapshot.get('snapshot_name', 'Snapshot')}")
    st.caption(asset_name)

    # ---- Section 1: Key Metrics ----
    st.markdown("### Key Metrics")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        npv_det = snapshot.get("npv_deterministic")
        st.metric(
            "Deterministic rNPV",
            f"{npv_det:,.1f}" if npv_det else "—",
            help="Risk-adjusted NPV in EUR mm",
        )
    with col2:
        npv_wi = snapshot.get("npv_deterministic_whatif")
        st.metric(
            "What-If rNPV",
            f"{npv_wi:,.1f}" if npv_wi else "—",
        )
    with col3:
        npv_mc = snapshot.get("npv_mc_average")
        st.metric(
            "MC Average rNPV",
            f"{npv_mc:,.1f}" if npv_mc else "—",
        )
    with col4:
        p50 = snapshot.get("npv_mc_p50")
        st.metric(
            "MC Median (P50)",
            f"{p50:,.1f}" if p50 else "—",
        )

    # MC percentiles row
    mc_cols = st.columns(5)
    percentile_fields = [
        ("P10", "npv_mc_p10"),
        ("P25", "npv_mc_p25"),
        ("P50", "npv_mc_p50"),
        ("P75", "npv_mc_p75"),
        ("P90", "npv_mc_p90"),
    ]
    for i, (label, field) in enumerate(percentile_fields):
        val = snapshot.get(field)
        mc_cols[i].metric(label, f"{val:,.1f}" if val else "—")

    st.divider()

    # ---- Section 2: Cashflow Table ----
    st.markdown("### Cashflow Table")

    try:
        cf_data = api.get_cashflows(snapshot_id, cashflow_type="deterministic", scope="Total")
        cashflows = cf_data.get("cashflows", [])
    except Exception:
        cashflows = []

    if cashflows:
        df_cf = pd.DataFrame(cashflows)
        df_cf.rename(columns={
            "year": "Year",
            "revenue": "Revenue",
            "costs": "Costs",
            "tax": "Tax",
            "fcf_non_risk_adj": "FCF (non-RA)",
            "risk_multiplier": "Risk Mult.",
            "fcf_risk_adj": "FCF (RA)",
            "fcf_pv": "PV",
        }, inplace=True)

        # Format numbers
        num_cols = ["Revenue", "Costs", "Tax", "FCF (non-RA)", "FCF (RA)", "PV"]
        for col in num_cols:
            if col in df_cf.columns:
                df_cf[col] = df_cf[col].apply(lambda x: f"{x:,.2f}")

        st.dataframe(df_cf, use_container_width=True, hide_index=True, height=400)

        # NPV total from cashflows
        total_pv = sum(cf.get("fcf_pv", 0) for cf in cashflows)
        st.info(f"Sum of PV (Total scope): **{total_pv:,.1f} EUR mm**")
    else:
        st.info("No cashflows calculated yet. Run Deterministic NPV first.")

    st.divider()

    # ---- Section 3: Charts ----
    if not HAS_PLOTLY:
        st.warning("Install plotly for interactive charts: `pip install plotly`")
        return

    st.markdown("### Charts")

    chart_tab1, chart_tab2, chart_tab3 = st.tabs([
        "Cashflow Waterfall",
        "MC Distribution",
        "Revenue by Region",
    ])

    # Chart 1: Cashflow Waterfall
    with chart_tab1:
        if cashflows:
            years = [cf["year"] for cf in cashflows]
            pvs = [cf["fcf_pv"] for cf in cashflows]

            colors = ["#EF4444" if pv < 0 else "#10B981" for pv in pvs]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=years, y=pvs,
                marker_color=colors,
                name="PV of FCF",
            ))

            # Cumulative line
            cumulative = []
            running = 0
            for pv in pvs:
                running += pv
                cumulative.append(running)

            fig.add_trace(go.Scatter(
                x=years, y=cumulative,
                mode="lines+markers",
                name="Cumulative NPV",
                line=dict(color="#1E3A5F", width=2),
            ))

            fig.update_layout(
                title="Annual Cashflow PV & Cumulative NPV",
                xaxis_title="Year",
                yaxis_title="EUR mm",
                template="plotly_white",
                height=450,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Run Deterministic NPV to see the cashflow waterfall.")

    # Chart 2: Monte Carlo Distribution
    with chart_tab2:
        mc_json = snapshot.get("mc_distribution_json")
        if mc_json:
            try:
                distribution = json.loads(mc_json)
                if distribution and len(distribution) > 1:
                    fig = go.Figure()

                    fig.add_trace(go.Histogram(
                        x=distribution,
                        nbinsx=50,
                        marker_color="#3B82F6",
                        opacity=0.8,
                        name="NPV Distribution",
                    ))

                    # Add percentile lines
                    p10 = snapshot.get("npv_mc_p10")
                    p50 = snapshot.get("npv_mc_p50")
                    p90 = snapshot.get("npv_mc_p90")

                    for val, label, color in [
                        (p10, "P10", "#EF4444"),
                        (p50, "P50", "#F59E0B"),
                        (p90, "P90", "#10B981"),
                    ]:
                        if val is not None:
                            fig.add_vline(
                                x=val,
                                line=dict(color=color, width=2, dash="dash"),
                                annotation_text=f"{label}: {val:,.0f}",
                            )

                    fig.update_layout(
                        title="Monte Carlo NPV Distribution",
                        xaxis_title="NPV (EUR mm)",
                        yaxis_title="Frequency",
                        template="plotly_white",
                        height=450,
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("MC distribution has no variance (no MC toggles enabled).")
            except (json.JSONDecodeError, TypeError):
                st.info("MC distribution data not available.")
        else:
            st.info("Run Monte Carlo to see the distribution chart.")

    # Chart 3: Revenue by Region
    with chart_tab3:
        try:
            # Get regional cashflows
            regions_to_check = ["US", "EU", "ROW", "China"]
            region_data = {}

            for region in regions_to_check:
                cf_region = api.get_cashflows(
                    snapshot_id, cashflow_type="deterministic", scope=region
                )
                regional_cfs = cf_region.get("cashflows", [])
                if regional_cfs:
                    region_data[region] = regional_cfs

            if region_data:
                fig = go.Figure()
                colors = {"US": "#3B82F6", "EU": "#10B981", "ROW": "#F59E0B", "China": "#EF4444"}

                for region, cfs in region_data.items():
                    years = [cf["year"] for cf in cfs]
                    revenues = [cf["revenue"] for cf in cfs]
                    fig.add_trace(go.Scatter(
                        x=years, y=revenues,
                        mode="lines+markers",
                        name=region,
                        line=dict(color=colors.get(region, "#6B7280"), width=2),
                    ))

                fig.update_layout(
                    title="Revenue by Region Over Time",
                    xaxis_title="Year",
                    yaxis_title="Revenue (EUR mm)",
                    template="plotly_white",
                    height=450,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No regional revenue data available.")
        except Exception as e:
            st.info(f"Revenue chart unavailable: {e}")

