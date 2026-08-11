@echo off
setlocal enabledelayedexpansion

echo ====================================================
echo   GridWatcher 1-Click Installer v2.0
echo ====================================================
echo.

REM --- Paths ---
set "SCRIPT_DIR=%~dp0"
set "TOOLS_DIR=%SCRIPT_DIR%tools"
set "CLI_EXE=%TOOLS_DIR%\arduino-cli.exe"
set "CLI_URL=https://downloads.arduino.cc/arduino-cli/arduino-cli_latest_Windows_64bit.zip"
set "CLI_ZIP=%TOOLS_DIR%\arduino-cli.zip"

echo [1/5] Installing Python dependencies...
python -m pip install PyQt5 pandas scikit-learn numpy paramiko --quiet
if errorlevel 1 (
    python -m pip install PyQt6 pandas scikit-learn numpy paramiko --quiet
)
echo        Done.
echo.

echo [2/5] Checking for arduino-cli...
if exist "%CLI_EXE%" (
    echo        arduino-cli already present at: %CLI_EXE%
    goto :boards
)

echo        Not found. Downloading arduino-cli standalone...
if not exist "%TOOLS_DIR%" mkdir "%TOOLS_DIR%"

REM Download arduino-cli using PowerShell
powershell -NoProfile -Command "Invoke-WebRequest -Uri '%CLI_URL%' -OutFile '%CLI_ZIP%' -UseBasicParsing"
if errorlevel 1 (
    echo        [ERROR] Failed to download arduino-cli. Check internet connection.
    pause
    exit /b 1
)

REM Extract arduino-cli.exe from zip
powershell -NoProfile -Command "Expand-Archive -Path '%CLI_ZIP%' -DestinationPath '%TOOLS_DIR%' -Force"
del "%CLI_ZIP%" 2>nul

if not exist "%CLI_EXE%" (
    echo        [ERROR] arduino-cli.exe not found after extraction.
    pause
    exit /b 1
)
echo        arduino-cli downloaded to: %CLI_EXE%
echo.

:boards
echo [3/5] Installing ESP32 board core (this may take 2-3 minutes)...
"%CLI_EXE%" config init --overwrite >nul 2>&1
"%CLI_EXE%" config add board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json >nul 2>&1

"%CLI_EXE%" core update-index >nul 2>&1
"%CLI_EXE%" core install esp32:esp32 2>&1
echo        ESP32 board core installed.
echo.

echo [4/5] Registering GridWatcher in Windows Startup...
set "TARGET_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SCRIPT_PATH=%SCRIPT_DIR%gridwatcher_ml_gui.py"
set "VBS_PATH=%TARGET_DIR%\GridWatcherML.vbs"

echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_PATH%"
echo WshShell.Run "python.exe """ ^& "%SCRIPT_PATH%" ^& """", 1, False >> "%VBS_PATH%"
echo        Startup entry registered.
echo.

echo ====================================================
echo   [5/5] INSTALL COMPLETE!
echo ====================================================
echo   arduino-cli : %CLI_EXE%
echo   Python deps : PyQt5, pandas, scikit-learn, numpy, paramiko
echo   ESP32 core  : installed
echo   Startup     : registered
echo.
echo   You can now double-click gridwatcher_ml_gui.py to run!
echo ====================================================
echo.
pause
