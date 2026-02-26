"""
PharmaPulse — Streamlit Frontend Application

Main entry point for the PharmaPulse web UI.

Usage:
    cd pharmapulse/frontend
    streamlit run app.py --server.port 8501
"""

import streamlit as st

# Page configuration — MUST be the first Streamlit command
st.set_page_config(
    page_title="PharmaPulse",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Import page modules
from tabs import portfolio_view, asset_inputs, asset_whatif, asset_results, portfolio_manager, chat_panel


def main():
    """Main application with tab navigation."""

    # Initialize session state
    if "selected_asset_id" not in st.session_state:
        st.session_state.selected_asset_id = None
    if "selected_snapshot_id" not in st.session_state:
        st.session_state.selected_snapshot_id = None
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = 0

    # Custom CSS for better styling
    st.markdown("""
    <style>
    /* Main header */
    .main-header {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1E3A5F;
        margin-bottom: 0;
        padding-bottom: 0;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #6B7280;
        margin-top: -10px;
    }
    /* Metric cards */
    div[data-testid="stMetric"] {
        background-color: #F0F4F8;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid #1E3A5F;
    }
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 20px;
        font-weight: 600;
    }
    /* Success/error badges */
    .badge-success {
        background-color: #DEF7EC;
        color: #03543F;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.8rem;
    }
    .badge-warning {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.8rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # Application header
    st.markdown('<p class="main-header">PharmaPulse</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="sub-header">R&D Portfolio Valuation Platform  |  '
        'Deterministic rNPV  |  Monte Carlo  |  What-If Analysis  |  Portfolio Strategy  |  AI Chat</p>',
        unsafe_allow_html=True,
    )

    # Tab navigation
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Portfolio View",
        "📝 Asset Inputs",
        "🔧 What-If Levers",
        "📈 Results & Charts",
        "🗂️ Portfolio Manager",
        "💬 AI Chat",
    ])

    with tab1:
        portfolio_view.render()

    with tab2:
        asset_inputs.render()

    with tab3:
        asset_whatif.render()

    with tab4:
        asset_results.render()

    with tab5:
        portfolio_manager.render()

    with tab6:
        chat_panel.render()


if __name__ == "__main__":
    main()

