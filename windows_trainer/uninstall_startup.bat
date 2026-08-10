@echo off
echo ====================================================
echo  Uninstalling GridWatcher Windows Startup Launcher 
echo ====================================================

set "TARGET_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=%TARGET_DIR%\GridWatcherML.vbs"

if exist "%VBS_PATH%" (
    del "%VBS_PATH%"
    echo Removed GridWatcherML.vbs from Startup folder!
    echo ====================================================
    echo   SUCCESS! GridWatcher removed from Startup.
    echo ====================================================
) else (
    echo GridWatcherML.vbs was not found in Startup folder.
)

echo.
pause
