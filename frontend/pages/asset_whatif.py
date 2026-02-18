"""Tab 3: What-If Scenario Analysis."""

import streamlit as st
import pandas as pd
import api_client
from components import cashflow_chart


def render():
    st.header("What-If Scenario Analysis")

    if "selected_asset_id" not in st.session_state:
        st.info("Select an asset from the Portfolio tab first.")
        return

    asset_id = st.session_state["selected_asset_id"]

    try:
        snapshots = api_client.list_snapshots(asset_id)
    except Exception as e:
        st.error(f"Backend error: {e}")
        return

    if not snapshots:
        st.info("No snapshots for this asset.")
        return

    snap_labels = {f"v{s['version']}: {s['label']}": s["id"] for s in snapshots}
    selected = st.selectbox("Base Snapshot", list(snap_labels.keys()), key="whatif_snap_select")
    snap_id = snap_labels[selected]
    snap = api_client.get_snapshot(snap_id)

    st.divider()
    st.subheader("Adjust Levers")

    c1, c2 = st.columns(2)
    with c1:
        peak_mult = st.slider("Peak Sales Multiplier", 0.5, 2.0, 1.0, 0.05, key="wi_peak")
        launch_delay = st.slider("Launch Delay (years)", -3, 5, 0, 1, key="wi_delay")
        dr_override = st.number_input("Discount Rate Override",
                                       value=snap["discount_rate"],
                                       min_value=0.0, max_value=0.30, step=0.01,
                                       format="%.2f", key="wi_dr")
    with c2:
        cogs_override = st.number_input("COGS % Override",
                                         value=snap["cogs_pct"],
                                         min_value=0.0, max_value=1.0, step=0.01,
                                         format="%.2f", key="wi_cogs")
        sga_override = st.number_input("SG&A % Override",
                                        value=snap["sga_pct"],
                                        min_value=0.0, max_value=1.0, step=0.01,
                                        format="%.2f", key="wi_sga")

    # POS overrides
    st.subheader("Phase POS Overrides")
    pos_overrides = {}
    if snap.get("phase_inputs"):
        cols = st.columns(len(snap["phase_inputs"]))
        for i, pi in enumerate(snap["phase_inputs"]):
            with cols[i]:
                new_pos = st.number_input(
                    pi["phase_name"],
                    value=pi["probability_of_success"],
                    min_value=0.0, max_value=1.0, step=0.05,
                    format="%.2f",
                    key=f"wi_pos_{pi['phase_name']}"
                )
                if abs(new_pos - pi["probability_of_success"]) > 0.001:
                    pos_overrides[pi["phase_name"]] = new_pos

    st.divider()

    if st.button("Run What-If NPV", type="primary", key="run_whatif"):
        # Save levers then run NPV
        levers = {
            "peak_sales_multiplier": peak_mult,
            "launch_delay_years": launch_delay,
            "discount_rate_override": dr_override if abs(dr_override - snap["discount_rate"]) > 0.001 else None,
            "cogs_pct_override": cogs_override if abs(cogs_override - snap["cogs_pct"]) > 0.001 else None,
            "sga_pct_override": sga_override if abs(sga_override - snap["sga_pct"]) > 0.001 else None,
            "pos_override": pos_overrides if pos_overrides else None,
        }

        try:
            # Apply levers by creating a temporary modified snapshot
            modified = {
                "peak_sales_usd_m": snap["peak_sales_usd_m"] * peak_mult,
                "launch_year": snap["launch_year"] + launch_delay,
                "patent_expiry_year": snap["patent_expiry_year"] + launch_delay,
                "discount_rate": dr_override,
                "cogs_pct": cogs_override,
                "sga_pct": sga_override,
                "whatif_levers": levers,
            }

            # Apply POS overrides to phase inputs
            if pos_overrides:
                new_phases = []
                for pi in snap["phase_inputs"]:
                    phase = dict(pi)
                    if pi["phase_name"] in pos_overrides:
                        phase["probability_of_success"] = pos_overrides[pi["phase_name"]]
                    new_phases.append({
                        "phase_name": phase["phase_name"],
                        "probability_of_success": phase["probability_of_success"],
                        "duration_years": phase["duration_years"],
                        "start_year": phase["start_year"],
                    })
                modified["phase_inputs"] = new_phases

            api_client.update_snapshot(snap_id, modified)
            result = api_client.run_deterministic_npv(snap_id)
            st.session_state["whatif_result"] = result
            st.success(f"What-If eNPV: **${result['enpv_usd_m']:,.1f}M**")
        except Exception as e:
            st.error(f"What-If failed: {e}")

    # Display results
    if "whatif_result" in st.session_state:
        result = st.session_state["whatif_result"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("eNPV", f"${result['enpv_usd_m']:,.1f}M")
        c2.metric("Unadj NPV", f"${result['unadjusted_npv_usd_m']:,.1f}M")
        c3.metric("cPOS", f"{result['cumulative_pos']:.2%}")
        c4.metric("Peak Sales", f"${result['peak_sales_usd_m']:,.0f}M")

        if result.get("cashflows"):
            st.plotly_chart(cashflow_chart(result["cashflows"]), use_container_width=True)

    # Monte Carlo section
    st.divider()
    st.subheader("Monte Carlo Simulation")

    mc1, mc2 = st.columns(2)
    with mc1:
        n_iter = st.number_input("Iterations", value=10000, min_value=1000, max_value=100000, step=1000, key="mc_iter")
    with mc2:
        mc_seed = st.number_input("Seed (0=random)", value=0, min_value=0, step=1, key="mc_seed")

    if st.button("Run Monte Carlo", key="run_mc"):
        # Save MC config
        mc_config = {
            "n_iterations": n_iter,
            "peak_sales_std_pct": 0.20,
            "launch_delay_std_years": 1.0,
            "pos_variation_pct": 0.10,
            "seed": mc_seed if mc_seed > 0 else None,
        }
        try:
            api_client.update_snapshot(snap_id, {"mc_config": mc_config})
            with st.spinner(f"Running {n_iter:,} simulations..."):
                mc_result = api_client.run_monte_carlo(snap_id)
            st.session_state["mc_result"] = mc_result
        except Exception as e:
            st.error(f"MC failed: {e}")

    if "mc_result" in st.session_state:
        mc = st.session_state["mc_result"]
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

        from components import mc_histogram
        st.plotly_chart(
            mc_histogram(mc["histogram_data"], mc["mean_npv"], mc["median_npv"]),
            use_container_width=True
        )
