@echo off
REM === Script pour lancer backend + frontend ===

REM Lancer le backend (FastAPI / Uvicorn) dans une nouvelle fenêtre PowerShell
start powershell -NoExit -Command "cd %~dp0; .\.venv\Scripts\Activate.ps1; python -m uvicorn backend.main:app --reload --port 8000"

REM Lancer le frontend (Streamlit) dans une nouvelle fenêtre PowerShell
start powershell -NoExit -Command "cd %~dp0; .\.venv\Scripts\Activate.ps1; $env:API_BASE='http://127.0.0.1:8000'; streamlit run frontend\streamlit_app.py"
