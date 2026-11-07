@echo off
setlocal
title Nivesh Control Room
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\activate.bat" (
  echo Python environment not found. See Setup in README.md.
  pause
  exit /b 1
)
call "backend\.venv\Scripts\activate.bat"

cd backend
python scripts\check_mongo.py
if errorlevel 1 (
  pause
  exit /b 1
)

if not exist "..\frontend\dist\index.html" (
  echo Building the frontend for the first time...
  pushd ..\frontend
  call npm run build
  popd
  if not exist "..\frontend\dist\index.html" (
    echo Frontend build failed. See the messages above.
    pause
    exit /b 1
  )
)

echo.
echo Nivesh Control Room: http://localhost:8000
echo Close this window to stop the app.
echo.
start "" /b python scripts\open_browser.py
python -m uvicorn app.main:app --port 8000 --log-level warning
