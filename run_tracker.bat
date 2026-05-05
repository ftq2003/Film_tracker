@echo off
REM ====================================================================
REM Film Tracker - one-click launcher for Windows
REM Place this file in the SAME folder as film_tracker.py
REM Double-click to run.
REM ====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo === Film Tracker Launcher ===
echo Working directory: %CD%
echo.

REM Verify film_tracker.py is here
if not exist "film_tracker.py" (
    echo ERROR: film_tracker.py not found in this folder.
    echo This .bat must be in the SAME folder as film_tracker.py.
    pause
    exit /b 1
)

REM Find Python (prefer miniconda directly to skip Microsoft Store stub)
set "PY_CMD="
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
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)
if not defined PY_CMD (
    echo ERROR: No working Python found.
    pause
    exit /b 1
)
echo Using Python: %PY_CMD%
"%PY_CMD%" --version
echo.

REM Step 1: Kill stale Chrome processes
echo [1/4] Closing stale Chrome processes...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

REM Step 2: Launch debug Chrome
echo [2/4] Launching debug Chrome on port 9222...
set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" (
    echo   ERROR: Chrome not found.
    pause
    exit /b 1
)
start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir=C:\chrome-tracker --no-first-run --no-default-browser-check

REM Step 3: Wait for Chrome
echo [3/4] Waiting for Chrome to come online...
set /a TRIES=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a TRIES+=1
powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:9222/json/version' -TimeoutSec 2 -UseBasicParsing).StatusCode } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    if !TRIES! LSS 15 goto wait_loop
    echo   WARNING: Chrome did not respond after 15 seconds.
    goto skip_ready_msg
)
echo   Chrome ready on port 9222.

:skip_ready_msg
echo.
echo Tip: visit bhphotovideo.com, adorama.com, freestylephoto.com,
echo and ebay.com once in the new Chrome to set cookies.
echo Solve any "press and hold" verifications.
echo.
echo Press any key to run the tracker...
pause >nul

REM Step 4: Run the tracker
echo [4/4] Running film tracker...
echo ============================================================
echo.

set PYTHONIOENCODING=utf-8

"%PY_CMD%" film_tracker.py %*
set "EXITCODE=!ERRORLEVEL!"

echo.
echo ============================================================
if !EXITCODE! NEQ 0 (
    echo.
    echo *** PYTHON EXITED WITH CODE !EXITCODE! ***
    echo Scroll up to see the error.
    echo.
) else (
    echo === Done ===
    echo The HTML report should have opened automatically.
    echo If not, open report.html in this folder.
)

echo.
echo Press any key to close this window...
pause >nul