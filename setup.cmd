@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
python -m venv .venv
if errorlevel 1 exit /b 1
:install
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 exit /b 1
echo.
echo Setup complete. Run run.cmd and open http://127.0.0.1:8000
