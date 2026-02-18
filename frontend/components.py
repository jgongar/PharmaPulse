"""Reusable UI components for PharmaPulse frontend."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px


def metric_card(label: str, value: str, delta: str = None):
    """Display a metric in a styled card."""
    st.metric(label=label, value=value, delta=delta)


def cashflow_chart(cashflows: list[dict]) -> go.Figure:
    """Create a cashflow waterfall chart."""
    if not cashflows:
        return go.Figure()

    df = pd.DataFrame(cashflows)
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["year"], y=df["rd_cost_usd_m"],
        name="R&D Cost", marker_color="#EF4444",
        hovertemplate="Year %{x}<br>R&D: $%{y:.1f}M<extra></extra>"
    ))
    fig.add_trace(go.Bar(
        x=df["year"], y=df["commercial_cf_usd_m"],
        name="Commercial CF", marker_color="#22C55E",
        hovertemplate="Year %{x}<br>Commercial: $%{y:.1f}M<extra></extra>"
    ))
    fig.add_trace(go.Scatter(
        x=df["year"], y=df["cumulative_npv_usd_m"],
        name="Cumulative NPV", mode="lines+markers",
        line=dict(color="#3B82F6", width=3),
        hovertemplate="Year %{x}<br>Cum NPV: $%{y:.1f}M<extra></extra>"
    ))

    fig.update_layout(
        title="Cashflow Timeline",
        xaxis_title="Year", yaxis_title="$M",
        barmode="relative",
        template="plotly_white",
        height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def tornado_chart(base_npv: float, sensitivities: dict) -> go.Figure:
    """Create a tornado sensitivity chart."""
    if not sensitivities:
        return go.Figure()

    labels = list(sensitivities.keys())
    low_vals = [s["low"] - base_npv for s in sensitivities.values()]
    high_vals = [s["high"] - base_npv for s in sensitivities.values()]

    # Sort by total range
    ranges = [abs(h - l) for h, l in zip(high_vals, low_vals)]
    sorted_idx = sorted(range(len(ranges)), key=lambda i: ranges[i])
    labels = [labels[i] for i in sorted_idx]
    low_vals = [low_vals[i] for i in sorted_idx]
    high_vals = [high_vals[i] for i in sorted_idx]

    fig = go.Figure()
    fig.add_trace(go.Bar(y=labels, x=low_vals, orientation="h", name="Downside", marker_color="#EF4444"))
    fig.add_trace(go.Bar(y=labels, x=high_vals, orientation="h", name="Upside", marker_color="#22C55E"))
    fig.update_layout(
        title="Sensitivity Tornado", xaxis_title="NPV Change ($M)",
        barmode="relative", template="plotly_white", height=400,
    )
    return fig


def mc_histogram(histogram_data: list[float], mean_npv: float, median_npv: float) -> go.Figure:
    """Create MC simulation histogram."""
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=histogram_data, nbinsx=50,
        marker_color="#6366F1", opacity=0.75,
        name="NPV Distribution"
    ))
    fig.add_vline(x=mean_npv, line_dash="dash", line_color="red",
                  annotation_text=f"Mean: ${mean_npv:.0f}M")
    fig.add_vline(x=median_npv, line_dash="dot", line_color="blue",
                  annotation_text=f"Median: ${median_npv:.0f}M")
    fig.update_layout(
        title="Monte Carlo NPV Distribution",
        xaxis_title="NPV ($M)", yaxis_title="Frequency",
        template="plotly_white", height=400,
    )
    return fig


def portfolio_bubble_chart(assets_data: list[dict]) -> go.Figure:
    """Create portfolio bubble chart (eNPV vs POS, size = peak sales)."""
    if not assets_data:
        return go.Figure()

    df = pd.DataFrame(assets_data)
    fig = px.scatter(
        df, x="cumulative_pos", y="enpv_usd_m",
        size="peak_sales_usd_m", color="therapeutic_area",
        hover_name="name", text="name",
        labels={"cumulative_pos": "Cumulative POS", "enpv_usd_m": "eNPV ($M)",
                "peak_sales_usd_m": "Peak Sales ($M)"},
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        title="Portfolio Overview: eNPV vs POS",
        template="plotly_white", height=500,
    )
    return fig
