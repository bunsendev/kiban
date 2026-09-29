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
set "PROBE_LOG=%LOGDIR%\powershell-probe-last.txt"
set "PROBE_MARKER=%LOGDIR%\powershell-probe-marker-last.txt"
set "FILE_PROBE_LOG=%LOGDIR%\powershell-file-probe-last.txt"
set "FILE_PROBE_SCRIPT=%LOGDIR%\powershell-file-probe.ps1"
set "FILE_PROBE_MARKER=%LOGDIR%\powershell-file-probe-marker-last.txt"
>"%LAUNCHLOG%" echo Started: %date% %time%
>>"%LAUNCHLOG%" echo Phase: launcher started
>>"%LAUNCHLOG%" echo Installer directory: %~dp0
if exist "%LOGDIR%\setup-last-error.txt" del /q "%LOGDIR%\setup-last-error.txt"
if exist "%LOGDIR%\setup-progress-last.txt" del /q "%LOGDIR%\setup-progress-last.txt"
if exist "%LOGDIR%\setup-transcript-last.txt" del /q "%LOGDIR%\setup-transcript-last.txt"
if exist "%LOGDIR%\field-pilot-setup-output-last.txt" del /q "%LOGDIR%\field-pilot-setup-output-last.txt"
if exist "%COMPLETE_MARKER%" del /q "%COMPLETE_MARKER%"
if exist "%PROBE_MARKER%" del /q "%PROBE_MARKER%"
if exist "%FILE_PROBE_MARKER%" del /q "%FILE_PROBE_MARKER%"
if exist "%PROBE_MARKER%" (
  >>"%LAUNCHLOG%" echo Phase: could not clear previous probe marker
  echo Cannot reset PowerShell diagnostics. Diagnostic folder: %LOGDIR%
  pause
  exit /b 1
)
if exist "%FILE_PROBE_MARKER%" (
  >>"%LAUNCHLOG%" echo Phase: could not clear previous file probe marker
  echo Cannot reset PowerShell file diagnostics. Diagnostic folder: %LOGDIR%
  pause
  exit /b 1
)
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
for %%F in ("%SETUP_SCRIPT%") do >>"%LAUNCHLOG%" echo Setup script bytes: %%~zF
>"%PSERROR%" echo PowerShell process stderr:
set "PSModulePath="
set "BUNSEN_INSTALL_PROBE_MARKER=%PROBE_MARKER%"
>>"%LAUNCHLOG%" echo Phase: starting PowerShell probe
"%POWERSHELL%" -NoProfile -Command "[IO.File]::WriteAllText($env:BUNSEN_INSTALL_PROBE_MARKER, 'POWERSHELL_OK ' + $PID + ' ' + $PSVersionTable.PSVersion.ToString())" >"%PROBE_LOG%" 2>&1
set "PROBE_CODE=%errorlevel%"
>>"%LAUNCHLOG%" echo Phase: PowerShell probe returned
>>"%LAUNCHLOG%" echo Probe exit code: %PROBE_CODE%
if not "%PROBE_CODE%"=="0" goto probe_failed
if not exist "%PROBE_MARKER%" goto probe_failed
>>"%LAUNCHLOG%" echo Phase: PowerShell probe marker confirmed
>"%FILE_PROBE_SCRIPT%" echo [IO.File]::WriteAllText^($env:BUNSEN_INSTALL_FILE_MARKER, 'FILE_OK'^)
if not exist "%FILE_PROBE_SCRIPT%" goto file_probe_failed
set "BUNSEN_INSTALL_FILE_MARKER=%FILE_PROBE_MARKER%"
>>"%LAUNCHLOG%" echo Phase: starting PowerShell -File probe
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%FILE_PROBE_SCRIPT%" >"%FILE_PROBE_LOG%" 2>&1
set "FILE_PROBE_CODE=%errorlevel%"
>>"%LAUNCHLOG%" echo Phase: PowerShell -File probe returned
>>"%LAUNCHLOG%" echo File probe exit code: %FILE_PROBE_CODE%
if not "%FILE_PROBE_CODE%"=="0" goto file_probe_failed
if not exist "%FILE_PROBE_MARKER%" goto file_probe_failed
>>"%LAUNCHLOG%" echo Phase: PowerShell -File probe marker confirmed
>>"%LAUNCHLOG%" echo Phase: starting PowerShell setup
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
:probe_failed
>>"%LAUNCHLOG%" echo Phase: PowerShell probe failed or marker missing
echo PowerShell did not complete its startup check.
echo Diagnostic folder: %LOGDIR%
echo Please take a photo of this window before closing it.
pause
exit /b 3
:file_probe_failed
>>"%LAUNCHLOG%" echo Phase: PowerShell -File probe failed or marker missing
echo PowerShell did not execute a simple script file.
echo Diagnostic folder: %LOGDIR%
echo Please take a photo of this window before closing it.
pause
exit /b 4
