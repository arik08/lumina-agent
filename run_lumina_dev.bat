@echo off
setlocal
:run_lumina
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\run_lumina.ps1" -Development
set "LUMINA_DEV_EXIT=%ERRORLEVEL%"
if "%LUMINA_DEV_EXIT%"=="76" (
    echo.
    echo [Lumina] Another launcher is already using the configured port. The existing runtime was left running.
    exit /b %LUMINA_DEV_EXIT%
)
if "%LUMINA_DEV_EXIT%"=="77" (
    echo.
    echo [Lumina] Another Backend owns the configured SQLite database. This launcher will close without retrying.
    exit /b %LUMINA_DEV_EXIT%
)
if "%LUMINA_DEV_EXIT%"=="78" exit /b 0
echo.
if not "%LUMINA_DEV_EXIT%"=="0" (
    echo [Lumina] Development launcher failed with exit code %LUMINA_DEV_EXIT%.
    echo [Lumina] Review the error above and data\logs\run_lumina_dev.state.json.
) else (
    echo [Lumina] Development launcher stopped.
)
echo [Lumina] Press R to restart. Press any other key to close this window.
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\Wait-LuminaLauncherRestart.ps1"
if "%ERRORLEVEL%"=="75" (
    echo.
    echo [Lumina] Restart requested.
    goto run_lumina
)
exit /b %LUMINA_DEV_EXIT%
