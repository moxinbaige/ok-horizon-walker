@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py --compatibility > "docs\compatibility_manual.log" 2>&1
if errorlevel 1 (
  echo NOT PASSED. See docs\compatibility_result.json.
) else (
  echo COMPLETED. See docs\compatibility_result.json.
)
pause
