@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\install_lumina.ps1" %*
exit /b %ERRORLEVEL%
