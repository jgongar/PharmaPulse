# PharmaPulse v3

A full-stack pharma R&D portfolio NPV platform for modeling, simulating, and analyzing drug development pipelines.

## Features

- **Deterministic rNPV Engine** — Risk-adjusted NPV with mid-year discounting, cumulative POS, linear/logistic uptake curves, and LOE erosion
- **Monte Carlo Simulation** — Stochastic modeling with configurable iterations, peak sales variance, launch delay, and POS perturbation
- **What-If Scenarios** — Adjust peak sales, launch timing, discount rates, COGS, SG&A, and phase POS via interactive sliders
- **Editable Inputs** — All snapshot parameters (R&D costs, phase success rates, commercial cashflows) are fully editable in the UI
- **Portfolio Aggregation** — Group assets into portfolios, run portfolio-level Monte Carlo with inter-asset correlation
- **Excel Export** — Download any snapshot as a multi-sheet Excel workbook
- **Chat Interface** — Natural language Q&A over portfolio data
- **MCP Server** — Model Context Protocol server for AI agent integration (Claude Desktop)
- **10 Sample Assets** — Pre-seeded database with 7 internal + 3 licensed pharma assets across multiple therapeutic areas

## Architecture

```
pharmapulse/
├── backend/              # FastAPI + SQLAlchemy + SQLite
│   ├── engines/          # NPV, Monte Carlo, What-If, Portfolio engines
│   ├── routers/          # REST API endpoints
│   ├── models.py         # ORM models
│   ├── schemas.py        # Pydantic schemas
│   ├── crud.py           # Database operations
│   ├── main.py           # FastAPI app entry point
│   └── seed_data.py      # Sample data seeder
├── frontend/             # Streamlit UI (6 tabs)
│   ├── pages/            # Portfolio Overview, Asset Inputs, What-If, Results, Portfolio Manager, Chat
│   ├── app.py            # Streamlit entry point
│   ├── api_client.py     # Backend API client
│   └── components.py     # Reusable chart components
├── mcp_server/           # MCP server for Claude Desktop
│   └── server.py         # FastMCP tool definitions
└── tests/                # Pytest suite (61 tests)
```

## Quick Start

### Prerequisites

- Python 3.11+ (tested on 3.14)
- Git

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/pharmapulse.git
cd pharmapulse

# Create virtual environment
python -m venv venv

# Activate it
# Windows:
.\venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

### 2. Seed the database

```bash
python -m backend.seed_data
```

This creates `backend/pharmapulse.db` with 10 sample pharma assets and runs NPV for all internal assets.

### 3. Start the backend

```bash
uvicorn backend.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 4. Start the frontend (new terminal)

```bash
cd frontend
streamlit run app.py --server.port 8501
```

Open: http://localhost:8501

### 5. (Optional) Start the MCP server

```bash
python mcp_server/server.py
```

## Running Tests

```bash
pip install pytest httpx
pytest tests/ -v
```

## Claude Desktop Integration (MCP)

PharmaPulse includes an MCP server that lets Claude Desktop query and analyze your portfolio directly.

### Setup

1. Make sure the **backend API is running** (step 3 above)

2. Add to your Claude Desktop config file:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "pharmapulse": {
      "command": "python",
      "args": ["C:/path/to/pharmapulse/mcp_server/server.py"]
    }
  }
}
```

> Replace the path with your actual installation path. On Windows, use the full path to `python.exe` inside your venv if needed.

3. Restart Claude Desktop — you should see the PharmaPulse tools (hammer icon)

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `list_assets` | List all pharma assets |
| `get_asset_detail` | Detailed asset info + NPV |
| `search_assets` | Search by name, TA, indication |
| `run_npv` | Deterministic risk-adjusted NPV |
| `run_monte_carlo` | Monte Carlo simulation |
| `compare_snapshots` | Side-by-side scenario comparison |
| `create_snapshot` | Create a new what-if scenario |
| `portfolio_summary` | Portfolio-level metrics |
| `run_portfolio_monte_carlo` | Portfolio simulation with correlation |

### Sample Prompts

See [PORTFOLIO_ANALYST_PROMPT.md](PORTFOLIO_ANALYST_PROMPT.md) for a full system prompt and example queries.

## Sample Data

| Asset | Therapeutic Area | Phase | Peak Sales | eNPV |
|-------|-----------------|-------|-----------|------|
| Nexovir | Oncology | P3 | $2,500M | $1,419M |
| Dermashield | Dermatology | Filing | $1,500M | $2,544M |
| Hepacure | Hepatology | P3 | $900M | $462M |
| Cardiozen | Cardiovascular | P2 | $1,800M | $283M |
| Neuralink-7 | Neuroscience | P1 | $4,000M | $235M |
| Inflammex | Immunology | P2 | $1,200M | $197M |
| Pulmofix | Respiratory | P2 | $800M | $103M |
| Oncobind (Licensed) | Oncology | P1 | $3,000M | — |
| Retinavue (Licensed) | Ophthalmology | P2 | $600M | — |
| Immunovax (Licensed) | Infectious Disease | P3 | $2,000M | — |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/assets/` | List all assets |
| POST | `/api/assets/` | Create asset |
| GET | `/api/snapshots/asset/{id}` | List snapshots for asset |
| POST | `/api/snapshots/` | Create snapshot (full nested JSON) |
| PUT | `/api/snapshots/{id}` | Update snapshot + children |
| POST | `/api/npv/deterministic/{id}` | Run deterministic NPV |
| POST | `/api/mc/run/{id}` | Run Monte Carlo |
| GET | `/api/export/excel/{id}` | Download Excel |
| GET | `/api/portfolios/{id}/summary` | Portfolio summary |
| POST | `/api/portfolios/{id}/montecarlo` | Portfolio MC simulation |

## Tech Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, SQLite, Pydantic v2
- **Frontend**: Streamlit, Plotly, Pandas
- **MCP**: FastMCP (Model Context Protocol SDK)
- **Tests**: Pytest (61 tests)

## License

MIT
