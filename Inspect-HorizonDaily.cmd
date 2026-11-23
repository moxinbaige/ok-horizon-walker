@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py --inspect > "docs\inspection_manual.log" 2>&1
if errorlevel 1 (
  echo FAILED. See docs\inspection_manual.log and screenshots.
) else (
  echo SUCCESS. See docs\inspection_result.json.
)
pause
