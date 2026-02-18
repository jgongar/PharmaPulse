"""Tab 5: Portfolio Manager — create, view, and simulate portfolios."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import api_client
from components import mc_histogram


def render():
    st.header("Portfolio Manager")

    try:
        assets = api_client.list_assets()
        portfolios = api_client.list_portfolios()
    except Exception as e:
        st.error(f"Cannot connect to backend: {e}")
        return

    # --- Create Portfolio ---
    with st.expander("Create New Portfolio", expanded=not portfolios):
        name = st.text_input("Portfolio Name", key="pf_name")
        desc = st.text_area("Description", key="pf_desc")

        # Select assets and their snapshots
        st.caption("Select snapshots to include:")
        selected_snapshots = []
        for asset in assets:
            snaps = api_client.list_snapshots(asset["id"])
            if snaps:
                snap_opts = {f"v{s['version']}: {s['label']}": s["id"] for s in snaps}
                col1, col2 = st.columns([1, 2])
                with col1:
                    include = st.checkbox(asset["name"], key=f"pf_inc_{asset['id']}")
                with col2:
                    if include:
                        chosen = st.selectbox(
                            "Snapshot", list(snap_opts.keys()),
                            key=f"pf_snap_{asset['id']}", label_visibility="collapsed"
                        )
                        selected_snapshots.append(snap_opts[chosen])

        if st.button("Create Portfolio", type="primary", key="create_pf"):
            if not name:
                st.error("Portfolio name is required.")
            elif not selected_snapshots:
                st.error("Select at least one snapshot.")
            else:
                try:
                    pf = api_client.create_portfolio({
                        "name": name,
                        "description": desc,
                        "snapshot_ids": selected_snapshots,
                    })
                    st.success(f"Portfolio '{pf['name']}' created with {len(selected_snapshots)} assets!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed: {e}")

    if not portfolios:
        st.info("No portfolios yet. Create one above.")
        return

    # --- Portfolio Selector ---
    st.divider()
    pf_names = {f"{p['name']} (ID:{p['id']})": p["id"] for p in portfolios}
    selected_pf_key = st.selectbox("Select Portfolio", list(pf_names.keys()), key="pf_select")
    pf_id = pf_names[selected_pf_key]

    col_del, _ = st.columns([1, 4])
    with col_del:
        if st.button("Delete Portfolio", key="del_pf"):
            api_client.delete_portfolio(pf_id)
            st.rerun()

    # --- Portfolio Summary ---
    try:
        summary = api_client.get_portfolio_summary(pf_id)
    except Exception as e:
        st.error(f"Failed to load summary: {e}")
        return

    st.subheader("Portfolio Summary")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total eNPV", f"${summary['total_enpv_usd_m']:,.1f}M")
    c2.metric("Assets", str(summary["num_assets"]))
    c3.metric("Mean eNPV", f"${summary.get('mean_enpv_usd_m', 0):,.1f}M")
    c4.metric("Total Peak Sales", f"${summary.get('total_peak_sales_usd_m', 0):,.0f}M")

    # Asset breakdown table
    if summary.get("assets"):
        asset_df = pd.DataFrame(summary["assets"])
        display_df = asset_df[["asset_name", "therapeutic_area", "current_phase",
                                "enpv_usd_m", "cumulative_pos", "peak_sales_usd_m", "launch_year"]].copy()
        display_df.columns = ["Asset", "TA", "Phase", "eNPV ($M)", "cPOS", "Peak Sales ($M)", "Launch"]
        st.dataframe(
            display_df.style.format({
                "eNPV ($M)": "${:,.1f}", "cPOS": "{:.2%}",
                "Peak Sales ($M)": "${:,.0f}",
            }),
            use_container_width=True, hide_index=True,
        )

    # TA / Phase distribution
    col_ta, col_phase = st.columns(2)
    with col_ta:
        ta_dist = summary.get("ta_distribution", {})
        if ta_dist:
            fig_ta = go.Figure(data=[go.Pie(labels=list(ta_dist.keys()), values=list(ta_dist.values()))])
            fig_ta.update_layout(title="By Therapeutic Area", height=300)
            st.plotly_chart(fig_ta, use_container_width=True)

    with col_phase:
        phase_dist = summary.get("phase_distribution", {})
        if phase_dist:
            fig_phase = go.Figure(data=[go.Pie(labels=list(phase_dist.keys()), values=list(phase_dist.values()))])
            fig_phase.update_layout(title="By Phase", height=300)
            st.plotly_chart(fig_phase, use_container_width=True)

    # --- Portfolio Cashflow Timeline ---
    st.divider()
    st.subheader("Portfolio Cashflow Timeline")
    try:
        pf_cashflows = api_client.get_portfolio_cashflows(pf_id)
        if pf_cashflows:
            cf_df = pd.DataFrame(pf_cashflows)
            fig_cf = go.Figure()
            fig_cf.add_trace(go.Bar(
                x=cf_df["year"], y=[-x for x in cf_df["total_rd_cost_usd_m"]],
                name="R&D Investment", marker_color="#EF4444"
            ))
            fig_cf.add_trace(go.Bar(
                x=cf_df["year"], y=cf_df["total_commercial_cf_usd_m"],
                name="Commercial CF", marker_color="#22C55E"
            ))
            fig_cf.add_trace(go.Scatter(
                x=cf_df["year"], y=cf_df["cumulative_pv_usd_m"],
                name="Cumulative PV", mode="lines+markers",
                line=dict(color="#3B82F6", width=3)
            ))
            fig_cf.update_layout(
                barmode="relative", template="plotly_white", height=400,
                xaxis_title="Year", yaxis_title="$M",
            )
            st.plotly_chart(fig_cf, use_container_width=True)
        else:
            st.info("No cashflow data. Run NPV for member assets first.")
    except Exception as e:
        st.warning(f"Could not load cashflows: {e}")

    # --- Portfolio Monte Carlo ---
    st.divider()
    st.subheader("Portfolio Monte Carlo Simulation")

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        pf_n_iter = st.number_input("Iterations", value=10000, min_value=1000,
                                     max_value=100000, step=1000, key="pf_mc_iter")
    with mc2:
        pf_corr = st.slider("Inter-asset Correlation", 0.0, 1.0, 0.0, 0.05, key="pf_mc_corr")
    with mc3:
        pf_seed = st.number_input("Seed (0=random)", value=0, min_value=0, step=1, key="pf_mc_seed")

    if st.button("Run Portfolio MC", type="primary", key="run_pf_mc"):
        try:
            with st.spinner(f"Simulating {pf_n_iter:,} iterations across {summary['num_assets']} assets..."):
                mc_result = api_client.run_portfolio_monte_carlo(
                    pf_id, pf_n_iter, pf_corr,
                    pf_seed if pf_seed > 0 else None
                )
            st.session_state["pf_mc_result"] = mc_result
        except Exception as e:
            st.error(f"MC failed: {e}")

    if "pf_mc_result" in st.session_state:
        mc = st.session_state["pf_mc_result"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mean NPV", f"${mc['mean_npv']:,.1f}M")
        c2.metric("Median NPV", f"${mc['median_npv']:,.1f}M")
        c3.metric("Std Dev", f"${mc['std_npv']:,.1f}M")
        c4.metric("P(NPV>0)", f"{mc['prob_positive']:.1%}")

        cc1, cc2, cc3, cc4 = st.columns(4)
        cc1.metric("P5", f"${mc['p5']:,.1f}M")
        cc2.metric("P25", f"${mc['p25']:,.1f}M")
        cc3.metric("P75", f"${mc['p75']:,.1f}M")
        cc4.metric("P95", f"${mc['p95']:,.1f}M")

        st.plotly_chart(
            mc_histogram(mc["histogram_data"], mc["mean_npv"], mc["median_npv"]),
            use_container_width=True,
        )
