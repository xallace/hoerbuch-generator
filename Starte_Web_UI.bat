@echo off
chcp 65001 >nul
title Hörbuch-Generator Studio (Stufe 2)
cd /d "%~dp0"
if exist "%~dp0python\python.exe" (
    "%~dp0python\python.exe" -I "%~dp0web.py" %*
) else (
    python -I "%~dp0web.py" %*
)
if %ERRORLEVEL% NEQ 0 pause
