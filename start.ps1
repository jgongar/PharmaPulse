# ============================================================
# PharmaPulse — Startup Script (PowerShell)
#
# Launches both the FastAPI backend and Streamlit frontend.
#
# Usage:
#   cd "Pharma Pulse v5/pharmapulse"
#   .\start.ps1
#
# Defaults:
#   Backend  → http://127.0.0.1:8050  (API docs at /docs)
#   Frontend → http://127.0.0.1:8501  (Streamlit UI)
#
# Press Ctrl+C in the PowerShell window to stop both servers.
# ============================================================

$ErrorActionPreference = "Stop"

# Configuration
$BACKEND_PORT  = 8050
$FRONTEND_PORT = 8501
$BACKEND_HOST  = "127.0.0.1"

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  PharmaPulse v5.0 — Starting Up" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Check Python is available
try {
    $pyVersion = python --version 2>&1
    Write-Host "[OK] Python: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+." -ForegroundColor Red
    exit 1
}

# Navigate to script directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir
Write-Host "[OK] Working directory: $(Get-Location)" -ForegroundColor Green

# Start Backend (FastAPI + Uvicorn)
Write-Host ""
Write-Host "Starting Backend API on http://${BACKEND_HOST}:${BACKEND_PORT} ..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
    param($dir, $host, $port)
    Set-Location $dir
    python -m uvicorn backend.main:app --host $host --port $port 2>&1
} -ArgumentList $scriptDir, $BACKEND_HOST, $BACKEND_PORT

# Wait a moment for backend to start
Start-Sleep -Seconds 3

# Check backend health
try {
    $health = Invoke-RestMethod -Uri "http://${BACKEND_HOST}:${BACKEND_PORT}/health" -TimeoutSec 5
    if ($health.status -eq "healthy") {
        Write-Host "[OK] Backend is healthy" -ForegroundColor Green
    }
} catch {
    Write-Host "[WARN] Backend health check failed - it may still be starting" -ForegroundColor Yellow
}

# Start Frontend (Streamlit)
Write-Host ""
Write-Host "Starting Streamlit Frontend on http://${BACKEND_HOST}:${FRONTEND_PORT} ..." -ForegroundColor Yellow
$frontendJob = Start-Job -ScriptBlock {
    param($dir, $port)
    Set-Location $dir
    python -m streamlit run frontend/app.py --server.port $port --server.headless true 2>&1
} -ArgumentList $scriptDir, $FRONTEND_PORT

# Wait a moment for frontend to start
Start-Sleep -Seconds 4

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "  PharmaPulse is running!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:  http://${BACKEND_HOST}:${FRONTEND_PORT}" -ForegroundColor White
Write-Host "  API Docs:  http://${BACKEND_HOST}:${BACKEND_PORT}/docs" -ForegroundColor White
Write-Host "  API Base:  http://${BACKEND_HOST}:${BACKEND_PORT}/api/" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop all servers." -ForegroundColor Gray
Write-Host ""

# Open browser
Start-Process "http://${BACKEND_HOST}:${FRONTEND_PORT}"

# Keep script alive and show logs
try {
    while ($true) {
        # Show any new backend output
        $backendOutput = Receive-Job -Job $backendJob -ErrorAction SilentlyContinue
        if ($backendOutput) {
            foreach ($line in $backendOutput) {
                Write-Host "[Backend] $line" -ForegroundColor DarkGray
            }
        }

        # Show any new frontend output
        $frontendOutput = Receive-Job -Job $frontendJob -ErrorAction SilentlyContinue
        if ($frontendOutput) {
            foreach ($line in $frontendOutput) {
                Write-Host "[Frontend] $line" -ForegroundColor DarkGray
            }
        }

        # Check if either job has stopped
        if ($backendJob.State -eq "Completed" -or $backendJob.State -eq "Failed") {
            Write-Host "[ERROR] Backend has stopped unexpectedly" -ForegroundColor Red
            Receive-Job -Job $backendJob
            break
        }
        if ($frontendJob.State -eq "Completed" -or $frontendJob.State -eq "Failed") {
            Write-Host "[ERROR] Frontend has stopped unexpectedly" -ForegroundColor Red
            Receive-Job -Job $frontendJob
            break
        }

        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host ""
    Write-Host "Shutting down PharmaPulse..." -ForegroundColor Yellow
    Stop-Job -Job $backendJob -ErrorAction SilentlyContinue
    Stop-Job -Job $frontendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $backendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $frontendJob -ErrorAction SilentlyContinue
    Write-Host "PharmaPulse stopped." -ForegroundColor Cyan
}

