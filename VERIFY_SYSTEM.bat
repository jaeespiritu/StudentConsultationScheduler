@echo off
cd /d "%~dp0"
title Campus Consultations - Offline Verification
where py >nul 2>nul
if not errorlevel 1 (
  py -3 VERIFY_SYSTEM.py
) else (
  python VERIFY_SYSTEM.py
)
echo.
pause
