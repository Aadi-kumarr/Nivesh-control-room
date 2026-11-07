@echo off
cd /d "%~dp0"
start "Nivesh API" cmd /k "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --port 8000"
start "Nivesh UI" cmd /k "cd /d "%~dp0frontend" && npm run dev"
echo API: http://localhost:8000   UI with hot reload: http://localhost:5173
