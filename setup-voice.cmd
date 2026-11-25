@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
call setup.cmd
if errorlevel 1 exit /b 1
:install
".venv\Scripts\python.exe" -m pip install -r requirements-voice-lock.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m scripts.check_voice
if errorlevel 1 exit /b 1
echo Voice dependencies are ready. Add credentials to .env and restart run.cmd.
