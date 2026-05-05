@echo off
REM ====================================================================
REM Film Tracker - Main runner
REM Designed to be friendly to non-technical users.
REM If something is missing, shows a Windows dialog instead of cryptic errors.
REM ====================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM Check that film_tracker.py exists in this folder
if not exist "film_tracker.py" (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('film_tracker.py is missing from this folder.`n`nMake sure run_tracker.bat is in the same folder as the rest of the Film Tracker files. If you downloaded a ZIP, you need to extract it first (don''t run from inside the ZIP).', 'Missing File', 'OK', 'Error')"
    exit /b 1
)

REM Find Python (prefer miniconda directly to avoid Microsoft Store stub)
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
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('Python is not installed.`n`nPlease run setup.bat first to install everything you need.', 'Setup Required', 'OK', 'Warning')"
    exit /b 1
)

REM Check that required packages are installed
"%PY_CMD%" -c "import bs4, pandas, curl_cffi, playwright" >nul 2>&1
if errorlevel 1 (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; $r = [System.Windows.Forms.MessageBox]::Show('Some required Python packages are not installed.`n`nClick OK to run setup.bat now to install them.', 'Setup Needed', 'OKCancel', 'Information'); if ($r -eq 'OK') { Start-Process 'setup.bat' } "
    exit /b 1
)

REM ============================================================
REM Open visible terminal so user can see progress
REM ============================================================

echo.
echo ============================================================
echo   FILM TRACKER
echo ============================================================
echo.

REM Step 1: Kill stale Chrome processes
echo [1/4] Closing stale Chrome processes...
taskkill /F /IM chrome.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

REM Step 2: Launch debug Chrome
echo [2/4] Opening Chrome...
set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME_PATH%" set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
set "CHROME_AVAILABLE=1"
if not exist "%CHROME_PATH%" (
    echo   Chrome not found. Will skip retailers that need it.
    set "CHROME_AVAILABLE=0"
) else (
    start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir=C:\chrome-tracker --no-first-run --no-default-browser-check
)

REM Step 3: Wait for Chrome
if "%CHROME_AVAILABLE%"=="1" (
    echo [3/4] Waiting for Chrome to be ready...
    set /a TRIES=0
    :wait_loop
    timeout /t 1 /nobreak >nul
    set /a TRIES+=1
    powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:9222/json/version' -TimeoutSec 2 -UseBasicParsing).StatusCode } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        if !TRIES! LSS 15 goto wait_loop
        echo   Chrome did not respond after 15 seconds. Continuing anyway.
    ) else (
        echo   Chrome ready.
    )
    echo.
    echo Tip: visit bhphotovideo.com, ebay.com once in the new Chrome
    echo to dismiss any "press and hold" verifications.
    echo.
    echo Press any key to start the tracker...
    pause >nul
) else (
    echo [3/4] Skipping Chrome step.
)

REM Step 4: Run the tracker
echo.
echo [4/4] Running tracker (5-15 minutes)...
echo ============================================================
echo.

set PYTHONIOENCODING=utf-8
"%PY_CMD%" film_tracker.py %*
set "EXITCODE=!ERRORLEVEL!"

echo.
echo ============================================================
if !EXITCODE! NEQ 0 (
    powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('The tracker ran into a problem. Scroll up in the black window to see the details.`n`nIf this keeps happening, take a screenshot of the black window and report it.', 'Something Went Wrong', 'OK', 'Error')"
) else (
    echo   Done! The report should have opened in your browser.
    echo   If it didn't, double-click report.html in this folder.
)

echo.
echo Press any key to close this window...
pause >nul