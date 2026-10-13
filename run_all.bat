@echo off
rem Start the KrishiSaathi API (port 8000) and frontend (port 8080) for local development.
rem First run creates backend\.venv and installs dependencies automatically.
setlocal
set "ROOT=%~dp0"

where python >nul 2>nul || (echo Python 3.10+ is required. & exit /b 1)
where npm >nul 2>nul || (echo Node.js 18+ is required. & exit /b 1)

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
  echo Creating backend virtual environment...
  python -m venv "%ROOT%backend\.venv" || exit /b 1
  "%ROOT%backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
  "%ROOT%backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%backend\requirements.txt" || exit /b 1
)
if not exist "%ROOT%Frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd "%ROOT%Frontend"
  call npm install || (popd & exit /b 1)
  popd
)

start "KrishiSaathi API" /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000"
start "KrishiSaathi Frontend" /D "%ROOT%Frontend" cmd /k "npm run dev"
echo.
echo API:      http://127.0.0.1:8000/docs
echo Frontend: http://localhost:8080
