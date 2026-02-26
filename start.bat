@echo off
REM ============================================================
REM PharmaPulse — Quick Start (Double-click to launch)
REM ============================================================

title PharmaPulse v6.0

echo.
echo ======================================
echo   PharmaPulse v6.0 -- Starting Up
echo ======================================
echo.

cd /d "%~dp0"

echo Starting Backend API on http://127.0.0.1:8050 ...
start "PharmaPulse Backend" /min cmd /c "C:\Users\jgong\AppData\Local\Python\bin\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8050"

timeout /t 3 /nobreak > nul

echo Starting Streamlit Frontend on http://127.0.0.1:8501 ...
start "PharmaPulse Frontend" /min cmd /c "C:\Users\jgong\AppData\Local\Python\bin\python.exe -m streamlit run frontend/app.py --server.port 8501 --server.headless true"

timeout /t 4 /nobreak > nul

echo.
echo ======================================
echo   PharmaPulse is running!
echo ======================================
echo.
echo   Frontend:  http://127.0.0.1:8501
echo   API Docs:  http://127.0.0.1:8050/docs
echo.

start http://127.0.0.1:8501

echo Press any key to STOP all servers...
pause > nul

echo.
echo Shutting down PharmaPulse...
taskkill /fi "WINDOWTITLE eq PharmaPulse Backend*" /f > nul 2>&1
taskkill /fi "WINDOWTITLE eq PharmaPulse Frontend*" /f > nul 2>&1
echo PharmaPulse stopped.

