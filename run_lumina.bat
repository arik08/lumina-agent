@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\run_lumina.ps1"
set "LUMINA_EXIT=%ERRORLEVEL%"
if "%LUMINA_EXIT%"=="78" exit /b 0
exit /b %LUMINA_EXIT%
