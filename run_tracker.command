#!/bin/bash
# ====================================================================
# Film Tracker - Main runner for macOS
# ====================================================================

cd "$(dirname "$0")"

# Function to show a Mac dialog
show_dialog() {
    local title="$1"
    local message="$2"
    local icon="$3"
    osascript <<EOF 2>/dev/null
display dialog "$message" with title "$title" buttons {"OK"} default button "OK" with icon $icon
EOF
}

# Check that film_tracker.py exists
if [ ! -f "film_tracker.py" ]; then
    show_dialog "Missing File" "film_tracker.py is not in this folder.\n\nMake sure run_tracker.command is in the same folder as the rest of the Film Tracker files. If you downloaded a ZIP, extract it first." stop
    exit 1
fi

# Find Python
PY_CMD=""
candidates=(
    "$HOME/miniconda3/bin/python3"
    "$HOME/anaconda3/bin/python3"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
)
for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then
        if "$candidate" -c "import sys" 2>/dev/null; then
            PY_CMD="$candidate"
            break
        fi
    fi
done
if [ -z "$PY_CMD" ]; then
    if command -v python3 >/dev/null 2>&1; then
        PY_CMD="python3"
    fi
fi

if [ -z "$PY_CMD" ]; then
    show_dialog "Setup Required" "Python is not installed.\n\nPlease run setup.command first to install everything you need." caution
    exit 1
fi

# Check that required packages are installed
if ! "$PY_CMD" -c "import bs4, pandas, curl_cffi, playwright" 2>/dev/null; then
    if osascript -e 'display dialog "Some required Python packages are not installed.\n\nClick OK to run setup.command now to install them." with title "Setup Needed" buttons {"Cancel", "OK"} default button "OK" with icon note' 2>/dev/null | grep -q "OK"; then
        chmod +x setup.command 2>/dev/null
        open setup.command
    fi
    exit 1
fi

echo
echo "============================================================"
echo "  FILM TRACKER"
echo "============================================================"
echo

# ============================================================
# Step 1: Kill stale Chrome processes (only the debug-tracker ones)
# ============================================================
echo "[1/4] Closing previous tracker Chrome (if any)..."
# Only kill Chrome processes that are using our specific user-data-dir
# This avoids killing the user's main Chrome browser
pkill -f "chrome-tracker" 2>/dev/null
sleep 2

# ============================================================
# Step 2: Launch debug Chrome
# ============================================================
echo "[2/4] Opening Chrome..."
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_AVAILABLE=1
if [ ! -f "$CHROME_PATH" ]; then
    echo "  Chrome not found. Will skip retailers that need it."
    CHROME_AVAILABLE=0
else
    "$CHROME_PATH" \
        --remote-debugging-port=9222 \
        --user-data-dir="$HOME/chrome-tracker" \
        --no-first-run \
        --no-default-browser-check \
        >/dev/null 2>&1 &
fi

# ============================================================
# Step 3: Wait for Chrome
# ============================================================
if [ "$CHROME_AVAILABLE" = "1" ]; then
    echo "[3/4] Waiting for Chrome to be ready..."
    TRIES=0
    while [ $TRIES -lt 15 ]; do
        sleep 1
        TRIES=$((TRIES + 1))
        if curl -s --max-time 2 http://localhost:9222/json/version >/dev/null 2>&1; then
            echo "  Chrome ready."
            break
        fi
    done
    if [ $TRIES -ge 15 ]; then
        echo "  Chrome did not respond after 15 seconds. Continuing anyway."
    fi
    echo
    echo "Tip: visit bhphotovideo.com, ebay.com once in the new Chrome window"
    echo "to dismiss any 'press and hold' verifications."
    echo
    echo "Press Enter to start the tracker..."
    read -r
else
    echo "[3/4] Skipping Chrome step."
fi

# ============================================================
# Step 4: Run the tracker
# ============================================================
echo
echo "[4/4] Running tracker (5-15 minutes)..."
echo "============================================================"
echo

export PYTHONIOENCODING=utf-8
"$PY_CMD" film_tracker.py "$@"
EXITCODE=$?

echo
echo "============================================================"
if [ $EXITCODE -ne 0 ]; then
    show_dialog "Something Went Wrong" "The tracker ran into a problem. Scroll up in the Terminal window to see the details.\n\nIf this keeps happening, take a screenshot of the Terminal output and report it." stop
else
    echo "  Done! The report should have opened in your browser."
    echo "  If it didn't, double-click report.html in this folder."
fi

echo
echo "Press any key to close this window..."
read -n 1 -s
