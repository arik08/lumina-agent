@echo off
setlocal
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0devtools\install_lumina.ps1" %*
set "LUMINA_INSTALL_EXIT=%ERRORLEVEL%"
if not "%LUMINA_INSTALL_EXIT%"=="0" (
    echo.
    echo [Lumina] Lumina installation failed with exit code %LUMINA_INSTALL_EXIT%.
    echo [Lumina] Review the error above, correct it, and run installer.bat again.
) else (
    echo.
    echo [Lumina] Lumina installation completed successfully.
    echo [Lumina] You can now run run_lumina.bat.
)
echo [Lumina] Press any key to close this window.
pause >nul
exit /b %LUMINA_INSTALL_EXIT%
