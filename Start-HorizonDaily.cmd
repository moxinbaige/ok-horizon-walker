@echo off
cd /d "%~dp0"
if exist "HorizonDaily.exe" (
  start "" "%~dp0HorizonDaily.exe"
  exit /b 0
)
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
