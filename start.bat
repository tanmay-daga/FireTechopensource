@echo off
rem Bug Buster launcher for Windows: double-click this file.
rem First run installs everything (a few minutes). Later runs start in seconds.
setlocal
cd /d "%~dp0"
set MODEL=gemma3:4b

where ollama >nul 2>&1
if errorlevel 1 (
  echo Ollama is not installed. Get it from https://ollama.com, then run this again.
  pause
  exit /b 1
)

set PY=py
where py >nul 2>&1
if errorlevel 1 set PY=python
%PY% --version >nul 2>&1
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org ^(tick "Add Python to PATH"^), then run this again.
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/4] Creating Python environment...
  %PY% -m venv backend\.venv
  if errorlevel 1 goto :fail
)
if not exist "backend\.venv\.installed" (
  echo [2/4] Installing backend packages ^(first run only^)...
  "backend\.venv\Scripts\python.exe" -m pip install -q -r backend\requirements.txt
  if errorlevel 1 goto :fail
  echo done > "backend\.venv\.installed"
)
if not exist "backend\.env" copy "backend\.env.example" "backend\.env" >nul

echo [3/4] Checking Ollama and the %MODEL% model...
ollama list >nul 2>&1
if errorlevel 1 (
  start "Ollama" /min ollama serve
  timeout /t 5 /nobreak >nul
)
ollama list | findstr /i /c:"%MODEL%" >nul
if errorlevel 1 (
  echo Downloading %MODEL% ^(about 3 GB, first run only^)...
  ollama pull %MODEL%
  if errorlevel 1 goto :fail
)

echo [4/4] Starting Bug Buster...
start "BugBuster Backend (port 8000)" /d "%~dp0backend" cmd /k ".venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000"
start "BugBuster Frontend (port 5500)" /d "%~dp0frontend" cmd /k "..\backend\.venv\Scripts\python.exe -m http.server 5500"
timeout /t 4 /nobreak >nul
start "" http://localhost:5500/exp.html

echo.
echo Bug Buster is running at http://localhost:5500
echo Close the two black windows ^(Backend and Frontend^) to stop it.
pause
exit /b 0

:fail
echo.
echo Something went wrong. Copy the red error text above and send it for help.
pause
exit /b 1
