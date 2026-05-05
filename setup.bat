@echo off
REM ====================================================================
REM Film Tracker - One-time setup script for new users
REM
REM This script:
REM   1. Checks if Python is installed (and finds the right one)
REM   2. Checks if Google Chrome is installed
REM   3. Installs all required Python packages
REM   4. Downloads Playwright's Chromium (needed as a fallback)
REM
REM Run this ONCE after cloning the repo. Then double-click run_tracker.bat
REM to actually run the tracker.
REM ====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ====================================================================
echo   Film Tracker Setup
echo ====================================================================
echo.

REM ============================================================
REM 1. Find a working Python installation
REM ============================================================
echo [1/4] Looking for Python...
set "PY_CMD="

REM Try miniconda3 first (most common for data science users)
if exist "%USERPROFILE%\miniconda3\python.exe" (
    "%USERPROFILE%\miniconda3\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=%USERPROFILE%\miniconda3\python.exe"
)
if not defined PY_CMD if exist "%USERPROFILE%\anaconda3\python.exe" (
    "%USERPROFILE%\anaconda3\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=%USERPROFILE%\anaconda3\python.exe"
)
if not defined PY_CMD if exist "C:\ProgramData\miniconda3\python.exe" (
    "C:\ProgramData\miniconda3\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=C:\ProgramData\miniconda3\python.exe"
)
if not defined PY_CMD if exist "C:\ProgramData\anaconda3\python.exe" (
    "C:\ProgramData\anaconda3\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=C:\ProgramData\anaconda3\python.exe"
)
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo.
    echo ERROR: No working Python installation found.
    echo.
    echo Please install Python 3.10 or later from one of:
    echo   - Miniconda ^(recommended^): https://docs.conda.io/en/latest/miniconda.html
    echo   - Python.org: https://www.python.org/downloads/
    echo.
    echo If installing from python.org, make sure to check "Add Python to PATH"
    echo during installation.
    echo.
    echo If you already have Python but Windows is showing a "Microsoft Store"
    echo stub instead, disable it via:
    echo   Settings -^> Apps -^> Advanced app settings -^> App execution aliases
    echo   Then turn OFF the "App Installer" entries for python.exe and python3.exe
    echo.
    pause
    exit /b 1
)

echo   Found Python at: %PY_CMD%
"%PY_CMD%" --version
echo.

REM ============================================================
REM 2. Verify Python version >= 3.10
REM ============================================================
echo [2/4] Checking Python version...
"%PY_CMD%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python version too old. This script needs Python 3.10 or later.
    echo Your Python:
    "%PY_CMD%" --version
    echo.
    pause
    exit /b 1
)
echo   Python version OK.
echo.

REM ============================================================
REM 3. Check for Google Chrome
REM ============================================================
echo [3/4] Checking for Google Chrome...
set "CHROME_FOUND=0"
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_FOUND=1"

if "%CHROME_FOUND%"=="0" (
    echo.
    echo WARNING: Google Chrome not found at standard locations.
    echo The tracker uses Chrome to handle bot-protected sites like B^&H.
    echo Without Chrome, those sites will be skipped.
    echo.
    echo Install from: https://www.google.com/chrome/
    echo.
    echo You can still proceed with setup, but bot-protected retailers will
    echo not work until Chrome is installed.
    echo.
    pause
) else (
    echo   Chrome found.
    echo.
)

REM ============================================================
REM 4. Install Python packages
REM ============================================================
echo [4/4] Installing Python packages...
echo   This may take a few minutes the first time.
echo.

"%PY_CMD%" -m pip install --quiet --upgrade pip
if errorlevel 1 (
    echo   WARNING: pip upgrade failed. Continuing with existing pip.
)

"%PY_CMD%" -m pip install --quiet curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed.
    echo.
    echo Try running this script as Administrator, or install manually:
    echo   "%PY_CMD%" -m pip install curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio
    echo.
    pause
    exit /b 1
)
echo   All Python packages installed successfully.
echo.

echo Installing Playwright's Chromium browser ^(used as a fallback for some sites^)...
echo This is a one-time download of about 150 MB.
"%PY_CMD%" -m playwright install chromium
if errorlevel 1 (
    echo.
    echo WARNING: Playwright Chromium install failed.
    echo The tracker will still work but with reduced fallback options.
    echo You can retry later with: "%PY_CMD%" -m playwright install chromium
    echo.
)

REM ============================================================
REM Done!
REM ============================================================
echo.
echo ====================================================================
echo   Setup complete!
echo ====================================================================
echo.
echo To run the tracker, double-click run_tracker.bat
echo.
echo First run will:
echo   1. Open a debug Chrome window
echo   2. Wait for you to visit B^&H, Adorama, eBay manually to set cookies
echo      ^(this only matters once a month or so^)
echo   3. Run discovery and check listings ^(takes 5-15 minutes^)
echo   4. Open the HTML report in your default browser
echo.
echo Edit config.txt after the first run to customize which retailers,
echo brands, and formats to track.
echo.
pause
