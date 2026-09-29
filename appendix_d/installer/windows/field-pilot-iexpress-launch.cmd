@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Bunsen Field Pilot Setup
set "LOGDIR=%LOCALAPPDATA%\Bunsen\FieldPilot\InstallerLogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LAUNCHLOG=%LOGDIR%\launcher-last.txt"
set "PSERROR=%LOGDIR%\powershell-stderr-last.txt"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
>"%LAUNCHLOG%" echo Started: %date% %time%
>>"%LAUNCHLOG%" echo Phase: launcher started
>>"%LAUNCHLOG%" echo Installer directory: %~dp0
if exist "%LOGDIR%\setup-last-error.txt" del /q "%LOGDIR%\setup-last-error.txt"
if exist "%LOGDIR%\setup-progress-last.txt" del /q "%LOGDIR%\setup-progress-last.txt"
if exist "%LOGDIR%\setup-transcript-last.txt" del /q "%LOGDIR%\setup-transcript-last.txt"
if not exist "%POWERSHELL%" (
  >>"%LAUNCHLOG%" echo Phase: PowerShell executable missing
  echo PowerShell was not found. Diagnostic folder: %LOGDIR%
  pause
  exit /b 1
)
>"%PSERROR%" echo PowerShell process stderr:
>>"%LAUNCHLOG%" echo Phase: starting PowerShell setup
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" 2>>"%PSERROR%"
set "SETUP_CODE=%errorlevel%"
>>"%LAUNCHLOG%" echo Phase: PowerShell returned
>>"%LAUNCHLOG%" echo Exit code: %SETUP_CODE%
>>"%LAUNCHLOG%" echo Finished: %date% %time%
if not "%SETUP_CODE%"=="0" (
  echo.
  echo Setup failed with exit code %SETUP_CODE%.
  echo Diagnostic folder: %LOGDIR%
  echo Please take a photo of this window before closing it.
  pause
)
exit /b %SETUP_CODE%
