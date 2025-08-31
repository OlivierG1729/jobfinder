# run_all.ps1
# Active l'environnement virtuel et lance backend + frontend dans deux fenêtres distinctes

$venvPath = ".\.venv\Scripts\Activate.ps1"

if (-Not (Test-Path $venvPath)) {
    Write-Host "⚠️ L'environnement virtuel .venv n'existe pas. Crée-le d'abord avec: python -m venv .venv"
    exit 1
}

# Lancer le backend dans une nouvelle fenêtre PowerShell
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$PWD`"; & { . $venvPath; python -m uvicorn backend.main:app --reload --port 8000 }"

# Lancer le frontend dans une nouvelle fenêtre PowerShell
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd `"$PWD`"; & { . $venvPath; $env:API_BASE='http://127.0.0.1:8000'; streamlit run frontend/streamlit_app.py }"

Write-Host "✅ Backend et frontend sont en cours de lancement dans deux fenêtres séparées."
