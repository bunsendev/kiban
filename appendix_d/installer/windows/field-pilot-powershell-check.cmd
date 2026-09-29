@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Bunsen PowerShell Check
set "LOGDIR=%LOCALAPPDATA%\Bunsen\FieldPilot\InstallerLogs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "PROBE_LOG=%LOGDIR%\standalone-powershell-check-last.txt"
set "PROBE_MARKER=%LOGDIR%\standalone-powershell-marker-last.txt"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%PROBE_MARKER%" del /q "%PROBE_MARKER%"
>"%PROBE_LOG%" echo Started: %date% %time%
>>"%PROBE_LOG%" echo PowerShell executable: %POWERSHELL%
if exist "%PROBE_MARKER%" (
  >>"%PROBE_LOG%" echo Could not clear previous marker
  goto finished
)
if not exist "%POWERSHELL%" (
  >>"%PROBE_LOG%" echo PowerShell executable missing
  goto finished
)
set "PSModulePath="
set "BUNSEN_INSTALL_PROBE_MARKER=%PROBE_MARKER%"
"%POWERSHELL%" -NoProfile -Command "[IO.File]::WriteAllText($env:BUNSEN_INSTALL_PROBE_MARKER, 'POWERSHELL_OK ' + $PID + ' ' + $PSVersionTable.PSVersion.ToString())" >>"%PROBE_LOG%" 2>&1
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
