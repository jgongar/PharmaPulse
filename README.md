# PharmaPulse v6

**AI-powered pharma R&D portfolio intelligence — Claude reasons over your pipeline.**

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.41-FF4B4B?logo=streamlit&logoColor=white)
![Claude AI](https://img.shields.io/badge/Claude-AI%20Analyst-8A2BE2?logo=anthropic&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

---

## What is PharmaPulse

PharmaPulse is a full-stack pharma R&D portfolio platform that combines rigorous financial
modeling (rNPV, Monte Carlo, mid-year discounting) with an embedded Claude AI analyst.
It ingests your drug development pipeline, runs six families of strategic simulations,
and surfaces insights through natural language — ask Claude which assets to kill, accelerate,
or acquire and get a data-grounded answer in seconds.

---

## AI at the Core

The centrepiece of PharmaPulse v6 is the **Claude-powered chat panel** embedded directly in the
Streamlit UI. Claude has access to **32 purpose-built API tools** covering every dimension of
portfolio analysis — it doesn't just answer questions, it executes simulations, builds portfolios,
runs Monte Carlo, compares scenarios, and saves results, all from a single conversation.

### How it works

```
User types a question
      ↓
Claude reasons over the portfolio context
      ↓
Claude calls PharmaPulse tools (run_npv, analyze_kill_impact, run_portfolio_simulation, ...)
      ↓
Results stream back into the conversation
      ↓
Claude synthesises a recommendation with actual numbers
```

### MCP Server for Claude Desktop

PharmaPulse also ships an **MCP (Model Context Protocol) server** — connect it to Claude Desktop
and analyse your pipeline in any conversation without opening the web app.

**Sample prompts that work out of the box:**
- *"Rank every asset by risk-adjusted NPV and flag the bottom quartile."*
- *"What's the portfolio impact if we kill Cardiozen today?"*
- *"Build an oncology sub-portfolio and run Monte Carlo at 20 % inter-asset correlation."*
- *"Identify our TA concentration risk and suggest rebalancing options."*

See [PORTFOLIO_ANALYST_PROMPT.md](PORTFOLIO_ANALYST_PROMPT.md) for the full system prompt.

---

## Key Capabilities

### Kill / Accelerate Analysis
Model the NPV impact of terminating a struggling asset or fast-tracking a high-value candidate.
Compare the freed R&D budget against opportunity cost and portfolio rebalancing scenarios.

### Therapeutic Area Budget Distribution
Visualise how R&D spend is allocated across TAs. Identify over-indexed areas, stress-test
budget cuts, and model reallocation to higher-return TAs.

### Temporal Balance
Assess launch cohort density across your planning horizon. Surface revenue-cliff risk when
multiple LOEs cluster in the same window and model pipeline-filling acquisitions.

### Innovation Risk Charter
Map assets on a risk/reward grid — incremental vs. first-in-class, near-term vs. speculative.
Quantify how a single BD deal or late-stage read-out shifts the portfolio risk profile.

### Business Development Modeling
Evaluate licensing deals, co-development agreements, and acquisitions as portfolio additions.
Model milestone payments, royalty structures, and upfront costs against projected rNPV.

### Concentration Risk Analysis
Measure Herfindahl-Hirschman Index (HHI) for TA, phase, and revenue concentration.
Run stress tests: "What if our top-3 assets all fail Phase 3?"

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Streamlit Frontend                  │
│  Asset Inputs │ Results │ Portfolio │ Chat Panel     │
└──────────────────────┬──────────────────────────────┘
                       │ REST API
┌──────────────────────▼──────────────────────────────┐
│                   FastAPI Backend                    │
│  /npv  /simulations  /portfolios  /snapshots  /query │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│               Simulation Engines                     │
│  deterministic · montecarlo · portfolio_sim          │
│  acceleration · ta_reallocation · temporal_balance   │
│  innovation_risk · bd_modeling · concentration       │
└──────────────────────┬──────────────────────────────┘
                       │
              ┌────────▼────────┐
              │  SQLite (rw)    │
              └─────────────────┘

          ┌──────────────────────────────┐
          │      Claude AI Layer         │
          │  Anthropic API  ←→  Chat UI  │
          │  MCP Server     ←→  Claude   │
          │                     Desktop  │
          └──────────────────────────────┘
```

---

## Financial Engine

| Feature | Detail |
|---------|--------|
| **Deterministic rNPV** | Cumulative POS × phase-gated cashflows, mid-year convention |
| **Revenue model** | Linear, logistic, or S-curve uptake; configurable LOE erosion |
| **Cost model** | Per-phase R&D costs, COGS %, SG&A % — all editable |
| **Monte Carlo** | 3-point (PERT) peak sales, Bernoulli POS perturbation, optional inter-asset correlation |
| **Portfolio simulation** | Aggregate eNPV distribution, P5/P50/P95, probability of portfolio NPV > 0 |
| **Discount rate** | Asset-level WACC; supports multi-rate portfolios |

---

## Quick Start

### Prerequisites

- Python 3.11+
- An Anthropic API key (for the chat panel)

### Install

```bash
git clone https://github.com/jgongar/PharmaPulse.git
cd PharmaPulse

python -m venv venv

# Windows
.\venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Seed the database

```bash
python -m backend.seed_data
```

Creates `backend/pharmapulse.db` with 10 sample pharma assets and computes base-case NPV for all internal assets.

### Start

```bash
# Terminal 1 — backend
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
streamlit run app.py --server.port 8501
```

| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| FastAPI docs | http://localhost:8000/docs |

### Anthropic API key

Set `ANTHROPIC_API_KEY` in your environment before starting the frontend
to enable the AI chat panel.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # macOS/Linux
set ANTHROPIC_API_KEY=sk-ant-...      # Windows cmd
$env:ANTHROPIC_API_KEY="sk-ant-..."   # PowerShell
```

---

## Project Structure

```
pharmapulse/
├── backend/
│   ├── engines/
│   │   ├── deterministic.py      # rNPV core
│   │   ├── montecarlo.py         # Stochastic simulation
│   │   ├── portfolio_sim.py      # Portfolio aggregation
│   │   ├── acceleration.py       # Kill / accelerate scenarios
│   │   ├── ta_reallocation.py    # TA budget redistribution
│   │   ├── temporal_balance.py   # Launch cohort analysis
│   │   ├── innovation_risk.py    # Risk/reward charter
│   │   ├── bd_modeling.py        # BD deal valuation
│   │   └── concentration.py      # HHI concentration metrics
│   ├── routers/
│   │   ├── npv.py                # NPV endpoints
│   │   ├── simulations.py        # Simulation families
│   │   ├── portfolios.py         # Portfolio CRUD + MC
│   │   ├── snapshots.py          # Scenario management
│   │   ├── query.py              # AI query support
│   │   └── export.py             # Excel export
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── crud.py
│   └── seed_data.py
├── frontend/
│   ├── tabs/
│   │   ├── asset_inputs.py       # Editable asset parameters
│   │   ├── asset_results.py      # NPV results & charts
│   │   ├── asset_whatif.py       # What-if scenario builder
│   │   ├── portfolio_manager.py  # Portfolio composition
│   │   ├── portfolio_view.py     # Portfolio analytics
│   │   └── chat_panel.py         # Claude AI chat panel
│   ├── chat/
│   │   ├── tool_definitions.py   # 32 Anthropic-format tools
│   │   ├── tool_executor.py      # Tool dispatch & API calls
│   │   └── llm_provider.py       # Anthropic API client
│   ├── app.py
│   └── api_client.py
├── mcp_server/
│   ├── server.py                 # FastMCP tool server
│   └── system_prompt.py         # Claude Desktop system prompt
├── tests/                        # Pytest suite
└── requirements.txt
```

---

## Tech Stack

| Layer | Library | Version |
|-------|---------|---------|
| Backend framework | FastAPI | 0.115.6 |
| ASGI server | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy | 2.0.36 |
| Validation | Pydantic | 2.10.4 |
| Frontend | Streamlit | 1.41.1 |
| Charts | Plotly | 5.24.1 |
| Data | Pandas / NumPy | 2.2.3 / 1.26.4 |
| Statistics | SciPy | 1.14.1 |
| AI SDK | Anthropic | 0.42.0 |
| MCP | FastMCP (mcp) | 1.2.0 |
| Export | openpyxl | 3.1.5 |
| Tests | Pytest | 8.3.4 |

---

## License

MIT
