@echo off
chcp 65001 >nul
set PSModulePath=
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\windows\field-pilot-setup.ps1"
if errorlevel 1 pause
