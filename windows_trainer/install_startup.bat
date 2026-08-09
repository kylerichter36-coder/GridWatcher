@echo off
echo ====================================================
echo   Installing GridWatcher Windows Startup Launcher   
echo ====================================================

set "TARGET_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SCRIPT_PATH=%~dp0gridwatcher_toast_launcher.py"
set "VBS_PATH=%TARGET_DIR%\GridWatcherML.vbs"

echo Creating background VBScript launcher in Startup folder...

(
echo Set WshShell = CreateObject("WScript.Shell"^)"
echo WshShell.Run "pythonw.exe """ ^& "%SCRIPT_PATH%" ^& """", 0, False
) > "%VBS_PATH%"

echo ====================================================
echo   SUCCESS! GridWatcher ML Trainer added to Startup! 
echo ====================================================
echo Whenever you log into Windows, it will ask if you want to retrain the ML model.
echo.
pause
