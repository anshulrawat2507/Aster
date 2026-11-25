@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
echo Run setup.cmd first.
exit /b 1
:run
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
