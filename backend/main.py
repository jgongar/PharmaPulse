"""
PharmaPulse Backend — FastAPI Application Entry Point

This is the main entry point for the PharmaPulse backend API server.
It configures the FastAPI application, includes all routers, sets up CORS,
and initializes the database on startup.

Architecture:
    - FastAPI application with auto-generated OpenAPI docs at /docs
    - CORS enabled for Streamlit frontend
    - All routers mounted under /api prefix
    - Database tables created on startup via lifespan event

Usage:
    python -m uvicorn backend.main:app --host 127.0.0.1 --port 8050
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import portfolio, snapshots, npv, export, portfolios, query, simulations


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    - On startup: initialize the database (create tables if they don't exist)
    - On shutdown: nothing special needed (SQLite handles cleanup)
    """
    init_db()
    yield


# Create FastAPI application
app = FastAPI(
    title="PharmaPulse Portfolio NPV Platform",
    description=(
        "REST API for pharmaceutical R&D portfolio valuation. "
        "Supports deterministic NPV, Monte Carlo simulation, "
        "what-if analysis, portfolio management, and strategy simulations."
    ),
    version="5.0.0",
    lifespan=lifespan,
)

# Configure CORS — allow Streamlit frontend on common ports
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",    # Streamlit default
        "http://127.0.0.1:8501",
        "http://localhost:8502",    # Streamlit alternate
        "http://127.0.0.1:8502",
        "http://localhost:8503",    # Streamlit alternate
        "http://127.0.0.1:8503",
        "http://localhost:3000",    # Optional: other frontends
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all routers
app.include_router(portfolio.router)   # /api/portfolio (asset CRUD)
app.include_router(snapshots.router)   # /api/snapshots
app.include_router(npv.router)         # /api/npv
app.include_router(export.router)      # /api/export
app.include_router(portfolios.router)  # /api/portfolios (portfolio CRUD + sim)
app.include_router(query.router)       # /api/query
app.include_router(simulations.router) # /api/simulations (Families A-F)


@app.get("/")
def root():
    """Health check and API information endpoint."""
    return {
        "name": "PharmaPulse API",
        "version": "5.0.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "assets": "/api/portfolio",
            "snapshots": "/api/snapshots/{asset_id}",
            "npv": "/api/npv/deterministic/{snapshot_id}",
            "portfolios": "/api/portfolios",
            "queries": "/api/query/assets",
            "export": "/api/export/cashflows/{snapshot_id}",
            "simulations": "/api/simulations/families",
        },
    }


@app.get("/health")
def health_check():
    """Simple health check for monitoring and MCP server connectivity."""
    return {"status": "healthy"}

