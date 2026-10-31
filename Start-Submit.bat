@echo off
title Hikvision ASMP Submit Tool
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Run: python setup_env.py
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "run.py" %*
if errorlevel 1 (
  echo.
  echo Run failed. See the application message or run python setup_env.py.
  pause
)
