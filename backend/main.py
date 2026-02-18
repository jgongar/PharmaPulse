"""FastAPI application entry point for PharmaPulse."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import portfolio, snapshots, npv, montecarlo, export, portfolios

app = FastAPI(title="PharmaPulse v3", version="3.0.0", description="Pharma R&D Portfolio NPV Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio.router)
app.include_router(snapshots.router)
app.include_router(npv.router)
app.include_router(montecarlo.router)
app.include_router(export.router)
app.include_router(portfolios.router)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def root():
    return {"app": "PharmaPulse v3", "status": "running"}


@app.get("/api/health")
def health():
    return {"status": "ok"}
