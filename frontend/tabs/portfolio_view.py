"""
Tab 1: Portfolio View — Overview of all assets in the portfolio.

Features:
- Filterable table of all assets (internal + competitors)
- Summary metrics bar
- Click-to-select navigation to Tab 2
- Create new asset buttons
"""

import streamlit as st
import pandas as pd
from frontend.api_client import api


def render():
    """Render the Portfolio View tab."""

    st.subheader("Portfolio Overview")

    # Filters
    col1, col2, col3 = st.columns([2, 2, 6])
    with col1:
        asset_filter = st.selectbox(
            "Asset Type",
            ["All", "Internal Only", "Competitors Only"],
            key="pv_asset_filter",
        )
    with col2:
        ta_filter = st.selectbox(
            "Therapeutic Area",
            ["All", "Immunology & Inflammation", "Oncology", "Neuroscience", "Hematology"],
            key="pv_ta_filter",
        )

    # Fetch assets from API
    try:
        params = {}
        if asset_filter == "Internal Only":
            params["is_internal"] = True
        elif asset_filter == "Competitors Only":
            params["is_internal"] = False

        ta_param = None if ta_filter == "All" else ta_filter
        assets = api.get_assets(
            is_internal=params.get("is_internal"),
            therapeutic_area=ta_param,
        )
    except Exception as e:
        st.error(f"Cannot connect to backend API: {e}")
        st.info("Make sure the backend is running: `uvicorn backend.main:app --port 8050`")
        return

    if not assets:
        st.info("No assets found. Create your first asset below.")
        _render_new_asset_form()
        return

    # Build DataFrame
    df = pd.DataFrame(assets)

    # Format display columns
    display_cols = {
        "id": "ID",
        "sponsor": "Sponsor",
        "compound_name": "Compound",
        "moa": "MoA",
        "therapeutic_area": "TA",
        "indication": "Indication",
        "current_phase": "Phase",
        "is_internal": "Internal",
        "peak_sales_estimate": "Peak Sales (EUR mm)",
        "launch_date": "Launch Date",
        "npv_deterministic": "rNPV Det. (EUR mm)",
        "npv_mc_average": "rNPV MC Avg (EUR mm)",
    }

    df_display = df[[c for c in display_cols.keys() if c in df.columns]].copy()
    df_display.rename(columns=display_cols, inplace=True)

    # Format numeric columns
    for col in ["Peak Sales (EUR mm)", "rNPV Det. (EUR mm)", "rNPV MC Avg (EUR mm)"]:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(
                lambda x: f"{x:,.1f}" if pd.notna(x) and x is not None else "—"
            )

    # Format boolean
    if "Internal" in df_display.columns:
        df_display["Internal"] = df_display["Internal"].apply(
            lambda x: "Yes" if x else "No"
        )

    # Display table
    st.dataframe(
        df_display,
        use_container_width=True,
        hide_index=True,
        height=min(400, 35 * len(df_display) + 40),
    )

    # Summary metrics
    internal_assets = [a for a in assets if a.get("is_internal")]
    competitor_assets = [a for a in assets if not a.get("is_internal")]

    # Calculate totals
    total_npv = sum(
        a.get("peak_sales_estimate") or 0
        for a in internal_assets
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Internal Assets", len(internal_assets))
    with col2:
        st.metric("Competitors", len(competitor_assets))
    with col3:
        st.metric("Total Assets", len(assets))
    with col4:
        st.metric("Total Peak Sales (Internal)", f"{total_npv:,.0f} EUR mm")

    st.divider()

    # Asset selection
    st.subheader("Select Asset for Detailed View")

    asset_options = {
        f"{a['compound_name']} — {a['indication']} ({a['current_phase']})": a["id"]
        for a in assets
    }

    selected = st.selectbox(
        "Choose an asset to view/edit:",
        options=list(asset_options.keys()),
        key="pv_asset_select",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Open Asset Workspace", type="primary", use_container_width=True):
            if selected:
                st.session_state.selected_asset_id = asset_options[selected]
                st.info(f"Asset selected! Navigate to the 'Asset Inputs' tab to view details.")

    with col2:
        if st.button("Run All Deterministic NPV", use_container_width=True):
            with st.spinner("Running deterministic NPV for all internal assets..."):
                results = []
                for a in internal_assets:
                    try:
                        snapshots = api.get_snapshots(a["id"])
                        if snapshots:
                            snap_id = snapshots[0]["id"]
                            result = api.run_deterministic_npv(snap_id)
                            results.append(f"{a['compound_name']}: {result['npv_deterministic']:,.1f} EUR mm")
                    except Exception as e:
                        results.append(f"{a['compound_name']}: Error - {e}")
                for r in results:
                    st.write(r)
                st.success("All NPV calculations complete! Refresh to see updated values.")

    with col3:
        if st.button("Duplicate Selected Asset", use_container_width=True):
            if selected:
                _duplicate_asset(asset_options[selected], assets)

    st.divider()

    # ---- Create New Asset ----
    _render_new_asset_form()


# ---------------------------------------------------------------------------
# New / Duplicate Asset Helpers
# ---------------------------------------------------------------------------

_PHASE_OPTIONS = ["Phase 1", "Phase 2", "Phase 2 B", "Phase 3", "Registration", "Approved"]
_TA_OPTIONS = [
    "Immunology & Inflammation", "Oncology", "Neuroscience",
    "Hematology", "Rare Disease", "Vaccines", "Other",
]


def _render_new_asset_form():
    """Collapsible form to create a new empty asset project."""
    with st.expander("➕ Create New Asset / Project", expanded=False):
        st.caption("Fill in the basic information to create a new drug asset. "
                   "You can add commercial forecast data in the Asset Inputs tab afterwards.")

        with st.form("new_asset_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                sponsor = st.text_input("Sponsor *", value="Sanofi")
                compound = st.text_input("Compound Name *", placeholder="e.g. PP-9999")
                moa = st.text_input("MoA", placeholder="e.g. Anti-IL-4Rα mAb")
            with col2:
                ta = st.selectbox("Therapeutic Area *", _TA_OPTIONS)
                indication = st.text_input("Indication *", placeholder="e.g. Atopic Dermatitis severe")
                phase = st.selectbox("Current Phase", _PHASE_OPTIONS, index=0)

            col3, col4 = st.columns(2)
            with col3:
                is_internal = st.checkbox("Internal asset", value=True)
                launch_date = st.number_input(
                    "Estimated Launch Year", min_value=2024.0, max_value=2060.0,
                    value=2030.0, step=0.25, format="%.2f",
                )
            with col4:
                pathway = st.text_input("Pathway", placeholder="e.g. Th2 pathway")
                innovation_class = st.selectbox("Innovation Class", ["standard", "first_in_class", "best_in_class"])

            create_snapshot_too = st.checkbox("Also create a default snapshot (recommended)", value=True)

            submitted = st.form_submit_button("Create Asset", type="primary")
            if submitted:
                if not compound or not indication:
                    st.error("Compound Name and Indication are required.")
                else:
                    _do_create_asset(
                        sponsor=sponsor,
                        compound_name=compound,
                        moa=moa,
                        therapeutic_area=ta,
                        indication=indication,
                        current_phase=phase,
                        is_internal=is_internal,
                        launch_date=launch_date,
                        pathway=pathway,
                        innovation_class=innovation_class,
                        create_snapshot=create_snapshot_too,
                    )


def _do_create_asset(*, sponsor, compound_name, moa, therapeutic_area,
                     indication, current_phase, is_internal, launch_date,
                     pathway, innovation_class, create_snapshot):
    """Create the asset (and optionally a default snapshot) via the API."""
    try:
        asset = api.create_asset({
            "sponsor": sponsor,
            "compound_name": compound_name,
            "moa": moa or None,
            "therapeutic_area": therapeutic_area,
            "indication": indication,
            "current_phase": current_phase,
            "is_internal": is_internal,
            "launch_date": launch_date,
            "pathway": pathway or None,
            "innovation_class": innovation_class,
        })
        st.success(f"Asset **{compound_name}** created (ID {asset['id']}).")

        if create_snapshot:
            # Create a bare-minimum snapshot
            snap = api.create_snapshot(asset["id"], {
                "snapshot_name": "Baseline v1",
                "description": f"Default snapshot for {compound_name}",
                "valuation_year": 2025,
                "horizon_years": 20,
                "wacc_rd": 0.10,
                "approval_date": launch_date,
                "phase_inputs": [
                    {"phase_name": current_phase, "start_date": 2025.0, "success_rate": 0.5},
                ],
                "rd_costs": [],
                "commercial_rows": [],
            })
            st.success(f"Default snapshot **Baseline v1** created (ID {snap['id']}). "
                       "Go to Asset Inputs to add commercial rows.")

        st.session_state.selected_asset_id = asset["id"]
        st.rerun()

    except Exception as e:
        st.error(f"Failed to create asset: {e}")


def _duplicate_asset(asset_id: int, all_assets: list):
    """
    Duplicate an existing asset — creates a new asset with all its data
    and clones the latest snapshot.
    """
    try:
        original = api.get_asset(asset_id)
        new_name = f"{original['compound_name']} (Copy)"

        # Create a copy of the asset
        new_asset = api.create_asset({
            "sponsor": original.get("sponsor", "Sanofi"),
            "compound_name": new_name,
            "moa": original.get("moa"),
            "therapeutic_area": original.get("therapeutic_area"),
            "indication": original.get("indication"),
            "current_phase": original.get("current_phase"),
            "is_internal": original.get("is_internal", True),
            "launch_date": original.get("launch_date"),
            "pathway": original.get("pathway"),
            "innovation_class": original.get("innovation_class", "standard"),
        })

        # Clone the latest snapshot to the new asset
        snapshots = api.get_snapshots(asset_id)
        if snapshots:
            latest_snap_id = snapshots[0]["id"]
            detail = api.get_snapshot_detail(latest_snap_id)
            snap_data = {
                "snapshot_name": f"Baseline v1",
                "description": f"Cloned from {original['compound_name']}",
                "valuation_year": detail.get("valuation_year", 2025),
                "horizon_years": detail.get("horizon_years", 20),
                "wacc_rd": detail.get("wacc_rd", 0.10),
                "approval_date": detail.get("approval_date", 2030.0),
                "phase_inputs": detail.get("phase_inputs", []),
                "rd_costs": detail.get("rd_costs", []),
                "commercial_rows": detail.get("commercial_rows", []),
            }
            # Add MC configs if present
            if detail.get("mc_commercial_config"):
                snap_data["mc_commercial_config"] = detail["mc_commercial_config"]
            if detail.get("mc_rd_configs"):
                snap_data["mc_rd_configs"] = detail["mc_rd_configs"]
            if detail.get("whatif_phase_levers"):
                snap_data["whatif_phase_levers"] = detail["whatif_phase_levers"]

            api.create_snapshot(new_asset["id"], snap_data)

        st.success(f"Duplicated as **{new_name}** (ID {new_asset['id']}).")
        st.session_state.selected_asset_id = new_asset["id"]
        st.rerun()

    except Exception as e:
        st.error(f"Failed to duplicate asset: {e}")

