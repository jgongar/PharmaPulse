"""Tab 6: Chat — Natural language Q&A over portfolio data."""

import streamlit as st
import pandas as pd
import api_client


def _get_portfolio_context() -> str:
    """Build a text summary of all assets and their NPVs for the chat context."""
    try:
        assets = api_client.list_assets()
    except Exception:
        return "No data available."

    lines = ["PharmaPulse Portfolio Summary:\n"]
    total_enpv = 0

    for asset in assets:
        snaps = api_client.list_snapshots(asset["id"])
        latest = snaps[-1] if snaps else None
        enpv = None
        cum_pos = None
        if latest and latest.get("cashflows"):
            cfs = latest["cashflows"]
            enpv = cfs[-1]["cumulative_npv_usd_m"] if cfs else None
            cum_pos = 1.0
            for pi in latest.get("phase_inputs", []):
                cum_pos *= pi["probability_of_success"]

        line = f"- {asset['name']} | TA: {asset['therapeutic_area']} | Phase: {asset['current_phase']}"
        if enpv is not None:
            line += f" | eNPV: ${enpv:,.1f}M | cPOS: {cum_pos:.1%}"
            line += f" | Peak Sales: ${latest['peak_sales_usd_m']:,.0f}M"
            line += f" | Launch: {latest['launch_year']}"
            total_enpv += enpv
        else:
            line += " | NPV: Not calculated"
        lines.append(line)

    lines.append(f"\nTotal Portfolio eNPV: ${total_enpv:,.1f}M")
    lines.append(f"Number of Assets: {len(assets)}")
    return "\n".join(lines)


def _answer_query(query: str, context: str) -> str:
    """Simple rule-based Q&A engine over portfolio data."""
    q = query.lower().strip()

    try:
        assets = api_client.list_assets()
    except Exception:
        return "Cannot connect to backend."

    # Build asset data for queries
    asset_data = []
    for asset in assets:
        snaps = api_client.list_snapshots(asset["id"])
        latest = snaps[-1] if snaps else None
        enpv = None
        cum_pos = None
        if latest and latest.get("cashflows"):
            cfs = latest["cashflows"]
            enpv = cfs[-1]["cumulative_npv_usd_m"] if cfs else 0
            cum_pos = 1.0
            for pi in latest.get("phase_inputs", []):
                cum_pos *= pi["probability_of_success"]

        asset_data.append({
            "name": asset["name"],
            "ta": asset["therapeutic_area"],
            "phase": asset["current_phase"],
            "is_internal": asset["is_internal"],
            "enpv": enpv,
            "cum_pos": cum_pos,
            "peak_sales": latest["peak_sales_usd_m"] if latest else 0,
            "launch_year": latest["launch_year"] if latest else 0,
        })

    calculated = [a for a in asset_data if a["enpv"] is not None]

    # Keyword-based routing
    if any(w in q for w in ["highest npv", "best npv", "top npv", "highest enpv", "most valuable"]):
        if calculated:
            best = max(calculated, key=lambda a: a["enpv"])
            return f"**{best['name']}** has the highest eNPV at **${best['enpv']:,.1f}M** (cPOS: {best['cum_pos']:.1%}, Peak Sales: ${best['peak_sales']:,.0f}M)."
        return "No NPV data available. Run NPV calculations first."

    if any(w in q for w in ["lowest npv", "worst npv", "bottom npv", "least valuable"]):
        if calculated:
            worst = min(calculated, key=lambda a: a["enpv"])
            return f"**{worst['name']}** has the lowest eNPV at **${worst['enpv']:,.1f}M** (cPOS: {worst['cum_pos']:.1%})."
        return "No NPV data available."

    if any(w in q for w in ["total npv", "portfolio npv", "total enpv", "portfolio value", "sum"]):
        if calculated:
            total = sum(a["enpv"] for a in calculated)
            return f"Total portfolio eNPV: **${total:,.1f}M** across {len(calculated)} assets with NPV data."
        return "No NPV data available."

    if any(w in q for w in ["how many", "count", "number of assets"]):
        internal = sum(1 for a in asset_data if a["is_internal"])
        external = len(asset_data) - internal
        return f"There are **{len(asset_data)} assets** total: {internal} internal and {external} licensed/external."

    if any(w in q for w in ["oncology", "cardiovascular", "neuro", "immuno", "hepat", "derm", "resp", "ophthal", "infect"]):
        for ta_keyword in ["oncology", "cardiovascular", "neuroscience", "immunology", "hepatology",
                           "dermatology", "respiratory", "ophthalmology", "infectious"]:
            if ta_keyword[:4] in q:
                matches = [a for a in asset_data if ta_keyword.lower() in a["ta"].lower()]
                if matches:
                    lines = [f"**{a['ta']}** assets:"]
                    for a in matches:
                        npv_str = f"${a['enpv']:,.1f}M" if a["enpv"] is not None else "Not calculated"
                        lines.append(f"- {a['name']} ({a['phase']}): eNPV {npv_str}")
                    return "\n".join(lines)
                return f"No assets found in that therapeutic area."

    if any(w in q for w in ["rank", "ranking", "list all", "show all", "all assets"]):
        if calculated:
            ranked = sorted(calculated, key=lambda a: a["enpv"], reverse=True)
            lines = ["**Portfolio Ranking by eNPV:**\n"]
            for i, a in enumerate(ranked, 1):
                lines.append(f"{i}. **{a['name']}** — ${a['enpv']:,.1f}M (cPOS: {a['cum_pos']:.1%})")
            return "\n".join(lines)
        return "No NPV data available."

    if any(w in q for w in ["phase 1", "p1", "phase 2", "p2", "phase 3", "p3", "filing"]):
        phase_map = {"p1": "P1", "phase 1": "P1", "p2": "P2", "phase 2": "P2",
                     "p3": "P3", "phase 3": "P3", "filing": "Filing"}
        target_phase = None
        for key, val in phase_map.items():
            if key in q:
                target_phase = val
                break
        if target_phase:
            matches = [a for a in asset_data if a["phase"] == target_phase]
            if matches:
                lines = [f"**{target_phase} assets:**\n"]
                for a in matches:
                    npv_str = f"${a['enpv']:,.1f}M" if a["enpv"] is not None else "Not calculated"
                    lines.append(f"- {a['name']} ({a['ta']}): eNPV {npv_str}")
                return "\n".join(lines)
            return f"No assets in {target_phase}."

    if any(w in q for w in ["launch", "when", "timeline"]):
        if calculated:
            sorted_by_launch = sorted(calculated, key=lambda a: a["launch_year"])
            lines = ["**Launch Timeline:**\n"]
            for a in sorted_by_launch:
                lines.append(f"- **{a['launch_year']}**: {a['name']} (eNPV: ${a['enpv']:,.1f}M)")
            return "\n".join(lines)
        return "No data available."

    if any(w in q for w in ["risk", "risky", "probability", "pos", "success"]):
        if calculated:
            sorted_by_pos = sorted(calculated, key=lambda a: a["cum_pos"])
            riskiest = sorted_by_pos[0]
            safest = sorted_by_pos[-1]
            return (
                f"**Riskiest:** {riskiest['name']} (cPOS: {riskiest['cum_pos']:.1%}, eNPV: ${riskiest['enpv']:,.1f}M)\n\n"
                f"**Safest:** {safest['name']} (cPOS: {safest['cum_pos']:.1%}, eNPV: ${safest['enpv']:,.1f}M)"
            )

    # Default: show context
    return (
        "I can answer questions about the portfolio. Try asking:\n"
        "- Which asset has the highest NPV?\n"
        "- How many assets are there?\n"
        "- Rank all assets by NPV\n"
        "- Show oncology assets\n"
        "- Which is the riskiest asset?\n"
        "- What's the launch timeline?\n"
        "- What's the total portfolio NPV?\n"
        "\n**Current Portfolio Data:**\n\n" + context
    )


def render():
    st.header("Portfolio Chat")
    st.caption("Ask questions about your pharma portfolio in natural language.")

    # Initialize chat history
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Display chat history
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Ask about your portfolio..."):
        # Add user message
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        context = _get_portfolio_context()
        response = _answer_query(prompt, context)

        st.session_state["chat_history"].append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            st.markdown(response)

    # Clear chat button in sidebar
    if st.sidebar.button("Clear Chat", key="clear_chat"):
        st.session_state["chat_history"] = []
        st.rerun()
