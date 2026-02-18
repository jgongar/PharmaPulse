"""PharmaPulse v3 — Streamlit Frontend Entry Point."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

st.set_page_config(
    page_title="PharmaPulse v3",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from pages import portfolio_view, asset_inputs, asset_whatif, asset_results, portfolio_manager, chat


def main():
    st.sidebar.title("PharmaPulse v3")
    st.sidebar.caption("Pharma R&D Portfolio NPV Platform")

    # Tab navigation
    tabs = [
        "Portfolio Overview",
        "Asset Inputs",
        "What-If Analysis",
        "NPV Results",
        "Portfolio Manager",
        "Chat",
    ]

    # Allow programmatic tab switching
    default_tab = st.session_state.get("active_tab", 0)
    if default_tab >= len(tabs):
        default_tab = 0

    selected_tab = st.sidebar.radio("Navigation", tabs, index=default_tab, key="nav_radio")
    tab_index = tabs.index(selected_tab)
    st.session_state["active_tab"] = tab_index

    # Sidebar info
    st.sidebar.divider()
    if "selected_asset_id" in st.session_state:
        st.sidebar.info(f"Selected Asset ID: {st.session_state['selected_asset_id']}")

    st.sidebar.divider()
    st.sidebar.caption("Backend: http://localhost:8000")
    st.sidebar.caption("API Docs: http://localhost:8000/docs")

    # Render selected tab
    if tab_index == 0:
        portfolio_view.render()
    elif tab_index == 1:
        asset_inputs.render()
    elif tab_index == 2:
        asset_whatif.render()
    elif tab_index == 3:
        asset_results.render()
    elif tab_index == 4:
        portfolio_manager.render()
    elif tab_index == 5:
        chat.render()


if __name__ == "__main__":
    main()
