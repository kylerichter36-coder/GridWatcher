@echo off
echo ====================================================
echo   GridWatcher Automated 1-Click Installer & Setup   
echo ====================================================

echo [1/3] Auto-installing required Python ML dependencies (PyQt6, pandas, scikit-learn, numpy)...
python -m pip install PyQt6 pandas scikit-learn numpy --quiet

set "TARGET_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SCRIPT_PATH=%~dp0gridwatcher_ml_gui.py"
set "VBS_PATH=%TARGET_DIR%\GridWatcherML.vbs"

echo [2/3] Registering GridWatcher Instant Dashboard in Windows Startup...

echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_PATH%"
echo WshShell.Run "python.exe """ ^& "%SCRIPT_PATH%" ^& """", 1, False >> "%VBS_PATH%"

echo ====================================================
echo   [3/3] SUCCESS! GridWatcher ML Trainer Installed!  
echo ====================================================
echo Every time you log into Windows, the instant PyQt6 dashboard will pop up automatically.
echo.
pause
