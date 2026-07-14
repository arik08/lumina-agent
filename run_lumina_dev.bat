@echo off
setlocal
:run_lumina
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\run_lumina.ps1" -Development
set "LUMINA_DEV_EXIT=%ERRORLEVEL%"
echo.
if not "%LUMINA_DEV_EXIT%"=="0" (
    echo [Lumina] Development launcher failed with exit code %LUMINA_DEV_EXIT%.
    echo [Lumina] Review the error above and data\logs\run_lumina_dev.state.json.
) else (
    echo [Lumina] Development launcher stopped.
)
echo [Lumina] Press r, R, or ㄱ to restart. Press any other key to close this window.
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\Wait-LuminaLauncherRestart.ps1"
if "%ERRORLEVEL%"=="75" (
    echo.
    echo [Lumina] Restart requested.
    goto run_lumina
)
exit /b %LUMINA_DEV_EXIT%
