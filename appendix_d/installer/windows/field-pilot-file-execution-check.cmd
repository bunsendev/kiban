@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Bunsen PowerShell File Check
set "LOGDIR=%LOCALAPPDATA%\Bunsen\FieldPilot\InstallerLogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "PROBE_LOG=%LOGDIR%\standalone-file-check-last.txt"
set "PROBE_SCRIPT=%LOGDIR%\standalone-file-check.ps1"
set "PROBE_MARKER=%LOGDIR%\standalone-file-marker-last.txt"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PROBE_MARKER%" del /q "%PROBE_MARKER%"
>"%PROBE_LOG%" echo Started: %date% %time%
if exist "%PROBE_MARKER%" (
  >>"%PROBE_LOG%" echo Could not clear previous marker
  goto finished
)
if not exist "%POWERSHELL%" (
  >>"%PROBE_LOG%" echo PowerShell executable missing
  goto finished
)
>"%PROBE_SCRIPT%" echo [IO.File]::WriteAllText^($env:BUNSEN_INSTALL_FILE_MARKER, 'FILE_OK'^)
if not exist "%PROBE_SCRIPT%" (
  >>"%PROBE_LOG%" echo Probe script could not be created
  goto finished
)
for %%F in ("%PROBE_SCRIPT%") do >>"%PROBE_LOG%" echo Probe script bytes: %%~zF
set "PSModulePath="
set "BUNSEN_INSTALL_FILE_MARKER=%PROBE_MARKER%"
>>"%PROBE_LOG%" echo Phase: starting PowerShell -File
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%PROBE_SCRIPT%" >>"%PROBE_LOG%" 2>&1
>>"%PROBE_LOG%" echo Exit code: %errorlevel%
if exist "%PROBE_MARKER%" (
  >>"%PROBE_LOG%" echo Marker: present
) else (
  >>"%PROBE_LOG%" echo Marker: missing
)
:finished
>>"%PROBE_LOG%" echo Finished: %date% %time%
echo Check completed. Diagnostic folder: %LOGDIR%
pause
