@echo off
title Hikvision ASMP Submit Tool
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -STA -File "ASMPSubmitTool.ps1"
if errorlevel 1 (
  echo.
  echo Run failed. Please make sure PowerShell is available on this computer.
  pause
)
