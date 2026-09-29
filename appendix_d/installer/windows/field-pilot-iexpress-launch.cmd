@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Bunsen Field Pilot Setup
set "LOGDIR=%LOCALAPPDATA%\Bunsen\FieldPilot\InstallerLogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LAUNCHLOG=%LOGDIR%\launcher-last.txt"
set "PSERROR=%LOGDIR%\powershell-stderr-last.txt"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "SETUP_SCRIPT=%~dp0install.ps1"
set "COMPLETE_MARKER=%LOGDIR%\setup-complete-last.txt"
>"%LAUNCHLOG%" echo Started: %date% %time%
>>"%LAUNCHLOG%" echo Phase: launcher started
>>"%LAUNCHLOG%" echo Installer directory: %~dp0
if exist "%LOGDIR%\setup-last-error.txt" del /q "%LOGDIR%\setup-last-error.txt"
if exist "%LOGDIR%\setup-progress-last.txt" del /q "%LOGDIR%\setup-progress-last.txt"
if exist "%LOGDIR%\setup-transcript-last.txt" del /q "%LOGDIR%\setup-transcript-last.txt"
if exist "%LOGDIR%\field-pilot-setup-output-last.txt" del /q "%LOGDIR%\field-pilot-setup-output-last.txt"
if exist "%COMPLETE_MARKER%" del /q "%COMPLETE_MARKER%"
if exist "%COMPLETE_MARKER%" (
  >>"%LAUNCHLOG%" echo Phase: could not clear previous completion marker
  echo Cannot reset installer diagnostics. Diagnostic folder: %LOGDIR%
  pause
  exit /b 1
)
if not exist "%POWERSHELL%" (
  >>"%LAUNCHLOG%" echo Phase: PowerShell executable missing
  echo PowerShell was not found. Diagnostic folder: %LOGDIR%
  pause
  exit /b 1
)
if not exist "%SETUP_SCRIPT%" (
  >>"%LAUNCHLOG%" echo Phase: install.ps1 missing from extracted package
  echo Installer script is missing. Diagnostic folder: %LOGDIR%
  pause
  exit /b 1
)
>"%PSERROR%" echo PowerShell process stderr:
>>"%LAUNCHLOG%" echo Phase: starting PowerShell setup
set "PSModulePath="
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%" 2>>"%PSERROR%"
set "SETUP_CODE=%errorlevel%"
>>"%LAUNCHLOG%" echo Phase: PowerShell returned
if "%SETUP_CODE%"=="0" if not exist "%COMPLETE_MARKER%" (
  >>"%LAUNCHLOG%" echo Phase: setup completion marker missing
  set "SETUP_CODE=2"
)
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
