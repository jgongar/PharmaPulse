"""
Tab 3: What-If Levers — Apply what-if scenario levers on top of a saved snapshot.

Features:
- Revenue lever slider
- R&D cost lever slider
- Phase-level SR override and duration change
- Run what-if NPV and compare with base
"""

import streamlit as st
import pandas as pd
from frontend.api_client import api


def render():
    """Render the What-If Levers tab."""

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
    asset_id = snapshot.get("asset_id")

    # Try to get asset name
    try:
        asset = api.get_asset(asset_id)
        asset_name = f"{asset['compound_name']} — {asset['indication']}"
    except Exception:
        asset_name = f"Asset {asset_id}"

    st.subheader(f"What-If Analysis — {snapshot.get('snapshot_name', 'Snapshot')}")
    st.caption(asset_name)

    # Current base NPV
    base_npv = snapshot.get("npv_deterministic")
    whatif_npv = snapshot.get("npv_deterministic_whatif")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Base Deterministic rNPV",
            f"{base_npv:,.1f} EUR mm" if base_npv else "Not calculated",
        )
    with col2:
        st.metric(
            "Current What-If rNPV",
            f"{whatif_npv:,.1f} EUR mm" if whatif_npv else "Not calculated",
            delta=f"{whatif_npv - base_npv:,.1f}" if whatif_npv and base_npv else None,
        )
    with col3:
        if base_npv and whatif_npv and base_npv != 0:
            pct_change = ((whatif_npv - base_npv) / abs(base_npv)) * 100
            st.metric("Impact", f"{pct_change:+.1f}%")
        else:
            st.metric("Impact", "—")

    st.divider()

    # ---- Revenue Lever ----
    st.markdown("### Revenue Lever")
    st.caption("Multiplier applied to ALL commercial revenue cashflows.")

    revenue_pct = st.slider(
        "Revenue adjustment (%)",
        min_value=-50, max_value=50, value=0, step=5,
        key="wi_revenue_slider",
        help="E.g., -10% means revenue × 0.9",
    )
    revenue_lever = 1.0 + (revenue_pct / 100.0)
    st.write(f"Revenue multiplier: **{revenue_lever:.2f}×**")

    # ---- R&D Cost Lever ----
    st.markdown("### R&D Cost Lever")
    st.caption("Multiplier applied to ALL R&D cost cashflows.")

    rd_pct = st.slider(
        "R&D cost adjustment (%)",
        min_value=-50, max_value=50, value=0, step=5,
        key="wi_rd_slider",
        help="E.g., +10% means R&D costs × 1.1",
    )
    rd_cost_lever = 1.0 + (rd_pct / 100.0)
    st.write(f"R&D cost multiplier: **{rd_cost_lever:.2f}×**")

    # ---- Phase-Level Levers ----
    st.markdown("### Phase-Level Levers")

    phases = detail.get("phase_inputs", [])
    phase_lever_data = []
    if phases:
        phase_names = [p["phase_name"] for p in phases]

        st.caption("Override success rate (SR) or add delay/acceleration per phase.")
        for phase in phases:
            col1, col2, col3 = st.columns([2, 3, 3])
            with col1:
                st.write(f"**{phase['phase_name']}**")
                st.caption(f"Base SR: {phase['success_rate']:.0%}")
            with col2:
                sr_override = st.number_input(
                    f"SR Override",
                    min_value=0.0, max_value=1.0,
                    value=float(phase["success_rate"]),
                    step=0.05,
                    key=f"wi_sr_{phase['phase_name']}",
                )
            with col3:
                duration_months = st.number_input(
                    f"Duration Change (months)",
                    min_value=-24, max_value=24, value=0, step=3,
                    key=f"wi_dur_{phase['phase_name']}",
                    help="Positive = delay, Negative = acceleration",
                )
            phase_lever_data.append({
                "phase_name": phase["phase_name"],
                "sr_override": sr_override if sr_override != phase["success_rate"] else None,
                "duration_months": duration_months,
            })

    st.divider()

    # ---- Action Buttons ----
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Apply & Run What-If NPV", type="primary", use_container_width=True):
            with st.spinner("Saving levers and recalculating what-if NPV..."):
                try:
                    # 1) Build phase lever payload
                    phase_lever_payload = []
                    for pld in phase_lever_data:
                        phase_lever_payload.append({
                            "phase_name": pld["phase_name"],
                            "lever_sr": pld["sr_override"],
                            "lever_duration_months": pld["duration_months"],
                        })

                    # 2) Save all lever values to the backend
                    api.save_whatif_levers(snapshot_id, {
                        "whatif_revenue_lever": revenue_lever,
                        "whatif_rd_cost_lever": rd_cost_lever,
                        "phase_levers": phase_lever_payload,
                    })

                    # 3) Now run the what-if calculation (reads saved levers)
                    result = api.run_deterministic_whatif(snapshot_id)
                    st.success(
                        f"What-If rNPV = {result['npv_deterministic']:,.1f} EUR mm"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"What-If calculation failed: {e}")

    with col2:
        if st.button("Reset All Levers", use_container_width=True):
            st.rerun()

    # ---- Sensitivity Summary ----
    st.markdown("### Quick Sensitivity Check")
    st.caption("See how individual lever changes affect NPV (one-at-a-time).")

    if base_npv:
        sensitivities = [
            ("Revenue -10%", 0.9, 1.0),
            ("Revenue +10%", 1.1, 1.0),
            ("R&D Cost +20%", 1.0, 1.2),
            ("R&D Cost -20%", 1.0, 0.8),
        ]

        sens_data = []
        for label, rev, rd in sensitivities:
            # Approximate impact
            if base_npv:
                # Simple linear approximation
                npv_rd_component = base_npv * 0.3  # Rough R&D weight
                npv_comm_component = base_npv * 0.7  # Rough commercial weight
                est_npv = npv_comm_component * rev + npv_rd_component * rd
                change = est_npv - base_npv
                sens_data.append({
                    "Scenario": label,
                    "Est. NPV (EUR mm)": f"{est_npv:,.1f}",
                    "Change (EUR mm)": f"{change:+,.1f}",
                })

        st.dataframe(pd.DataFrame(sens_data), use_container_width=True, hide_index=True)

