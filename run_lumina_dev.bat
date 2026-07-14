@echo off
setlocal
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\run_lumina.ps1" -Development
set "LUMINA_DEV_EXIT=%ERRORLEVEL%"
echo.
if not "%LUMINA_DEV_EXIT%"=="0" (
    echo [Lumina] Development launcher failed with exit code %LUMINA_DEV_EXIT%.
    echo [Lumina] Review the error above and data\logs\run_lumina_dev.state.json.
) else (
    echo [Lumina] Development launcher stopped.
)
echo [Lumina] Press any key to close this window.
pause >nul
exit /b %LUMINA_DEV_EXIT%
