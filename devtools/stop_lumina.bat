@echo off
setlocal

rem Move away from the repository before cleanup so this wrapper does not keep
rem the Lumina folder locked while the PowerShell cleanup runs.
pushd "%TEMP%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_lumina.ps1" %*
set "LUMINA_STOP_EXIT=%ERRORLEVEL%"
popd >nul 2>&1

if not "%LUMINA_STOP_EXIT%"=="0" (
    echo.
    echo [Lumina] Cleanup failed with exit code %LUMINA_STOP_EXIT%.
    echo [Lumina] Review the error above, then press any key to close.
    pause >nul
)

exit /b %LUMINA_STOP_EXIT%
