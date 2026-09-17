@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\windows\analysis-start.ps1" -IncludeTimesFm
pause
