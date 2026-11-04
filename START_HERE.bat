@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Student Consultation Scheduler - Local
color 0B
echo.
echo  =======================================================
echo    STUDENT CONSULTATION SCHEDULER - CLICK TO START
 echo   Local SQLite - no Node.js, npm, pip, or MongoDB
 echo  =======================================================
echo.
REM Like BLOOM, this launcher uses Python already on your Windows PC.
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD goto MissingPython
%PY_CMD% -c "import sys, sqlite3; assert sys.version_info >= (3,9)" >nul 2>nul
if errorlevel 1 goto MissingPython
echo Starting local website and SQLite database...
echo Your browser will open automatically.
echo Keep this window open. Close it to stop the website.
echo.
%PY_CMD% app.py
if errorlevel 1 goto Failed
exit /b 0
:MissingPython
echo Python 3.9+ could not be found on your computer.
echo This project uses the same Python launcher approach as BLOOM.
echo BLOOM also needs Python. No additional Python packages are needed here.
echo If BLOOM already works, confirm the Python command works in this terminal.
goto End
:Failed
echo Could not start the app. The window above should show what happened.
echo If port 8443 is occupied, close the other scheduler and try again.
:End
pause
exit /b 1
