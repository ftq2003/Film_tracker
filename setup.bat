@echo off
REM ====================================================================
REM Film Tracker - First-time setup
REM Designed to be friendly to non-technical users.
REM Uses Windows dialog boxes instead of terminal-only error messages.
REM ====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   FILM TRACKER - First-time Setup
echo ============================================================
echo   This sets up everything you need.
echo   It only needs to run once.
echo ============================================================
echo.

REM ============================================================
REM Step 1: Check for Python
REM ============================================================
echo [1/3] Looking for Python...
set "PY_CMD="

if exist "%USERPROFILE%\miniconda3\python.exe" (
    "%USERPROFILE%\miniconda3\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=%USERPROFILE%\miniconda3\python.exe"
)
if not defined PY_CMD if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=%USERPROFILE%\anaconda3\python.exe"
)
if not defined PY_CMD if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" (
    set "PY_CMD=%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe"
)
if not defined PY_CMD if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe" (
    set "PY_CMD=%USERPROFILE%\AppData\Local\Programs\Python\Python311\python.exe"
)
if not defined PY_CMD if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe" (
    set "PY_CMD=%USERPROFILE%\AppData\Local\Programs\Python\Python310\python.exe"
)
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    REM Show a Windows dialog explaining what to do
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $r = [System.Windows.Forms.MessageBox]::Show('Python is not installed on this computer.`n`nFilm Tracker needs Python 3.10 or newer. Click OK to open the Python download page in your browser.`n`nAfter installing:`n  1. IMPORTANT: Check the box `"Add Python to PATH`" during installation`n  2. Come back to this folder and double-click setup.bat again', 'Python Required', 'OKCancel', 'Information'); if ($r -eq 'OK') { Start-Process 'https://www.python.org/downloads/' }"
    echo.
    echo Setup paused. Install Python, then run setup.bat again.
    pause
    exit /b 1
)
echo   Found Python: %PY_CMD%
"%PY_CMD%" --version
echo.

REM ============================================================
REM Step 2: Check for Chrome
REM ============================================================
echo [2/3] Looking for Google Chrome...
set "CHROME_FOUND=0"
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"

if "%CHROME_FOUND%"=="0" (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $r = [System.Windows.Forms.MessageBox]::Show('Google Chrome is not installed on this computer.`n`nFilm Tracker uses Chrome to handle some retailers (B&H, KEH) that have anti-bot protection. Without Chrome, those will be skipped.`n`nClick OK to open the Chrome download page, or Cancel to continue without Chrome.', 'Chrome Recommended', 'OKCancel', 'Warning'); if ($r -eq 'OK') { Start-Process 'https://www.google.com/chrome/' }"
    echo.
    echo Continuing without Chrome. Some retailers will be skipped.
    timeout /t 3 /nobreak >nul
) else (
    echo   Chrome found.
)
echo.

REM ============================================================
REM Step 3: Install required Python packages
REM ============================================================
echo [3/3] Installing required Python packages...
echo   First time this may take a few minutes. Please wait.
echo.

"%PY_CMD%" -m pip install --quiet --upgrade pip >nul 2>&1
"%PY_CMD%" -m pip install --quiet curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio
if errorlevel 1 (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Could not install Python packages.`n`nThis is usually a network problem or a permission issue.`n`nTry:`n  1. Make sure your internet is connected`n  2. Run setup.bat as Administrator (right-click, Run as administrator)`n  3. Try again', 'Installation Failed', 'OK', 'Error')"
    pause
    exit /b 1
)
echo   Python packages installed.
echo.

echo Installing Chromium browser for Playwright (one-time, ~150 MB)...
"%PY_CMD%" -m playwright install chromium >nul 2>&1
if errorlevel 1 (
    echo   Warning: Chromium download failed. Tracker will still work but with reduced fallback options.
) else (
    echo   Chromium installed.
)
echo.

REM ============================================================
REM All done - show success dialog
REM ============================================================
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Setup is complete!`n`nTo use the tracker:`n  Double-click `"run_tracker.bat`"`n`nFirst run will:`n  1. Open a Chrome window (this is normal)`n  2. Run for 5-15 minutes searching retailers`n  3. Automatically open the report in your browser`n`nAfter the first run, edit `"config.txt`" to customize what gets searched.', 'Setup Complete', 'OK', 'Information')"

echo ============================================================
echo   Setup complete! Double-click run_tracker.bat to start.
echo ============================================================
echo.
pause
