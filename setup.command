#!/bin/bash
# ====================================================================
# Film Tracker - First-time setup for macOS
# Designed to be friendly to non-technical users.
# Uses macOS dialog boxes via osascript for errors.
# ====================================================================

# Move to the script's directory regardless of where it was launched from
cd "$(dirname "$0")"

# Function to show a Mac dialog box
show_dialog() {
    local title="$1"
    local message="$2"
    local icon="$3"   # caution / stop / note
    osascript <<EOF
display dialog "$message" with title "$title" buttons {"OK"} default button "OK" with icon $icon
EOF
}

# Function to show a dialog with Yes/No and return 0 (yes) or 1 (no)
show_yes_no() {
    local title="$1"
    local message="$2"
    local result
    result=$(osascript <<EOF
display dialog "$message" with title "$title" buttons {"Cancel", "OK"} default button "OK" with icon note
EOF
2>/dev/null)
    if [[ "$result" == *"OK"* ]]; then
        return 0
    else
        return 1
    fi
}

echo
echo "============================================================"
echo "  FILM TRACKER - First-time Setup (macOS)"
echo "============================================================"
echo "  This sets up everything you need."
echo "  It only needs to run once."
echo "============================================================"
echo

# ============================================================
# Step 1: Find a working Python
# ============================================================
echo "[1/3] Looking for Python..."
PY_CMD=""

# Try common Python locations on Mac, in order of preference
candidates=(
    "$HOME/miniconda3/bin/python3"
    "$HOME/anaconda3/bin/python3"
    "/opt/homebrew/bin/python3"        # Apple Silicon Homebrew
    "/usr/local/bin/python3"           # Intel Homebrew
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3"
    "/usr/bin/python3"                 # macOS system python (may be too old)
)

for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ]; then
        # Test it actually works AND is version 3.10+
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            PY_CMD="$candidate"
            break
        fi
    fi
done

# Fallback: try `python3` on PATH
if [ -z "$PY_CMD" ]; then
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            PY_CMD="python3"
        fi
    fi
fi

if [ -z "$PY_CMD" ]; then
    echo "  Python 3.10+ not found."
    if show_yes_no "Python Required" "Python 3.10 or newer is not installed.\n\nFilm Tracker needs Python to run. Click OK to open the Python download page in your browser.\n\nAfter installing Python, come back to this folder and double-click setup.command again."; then
        open "https://www.python.org/downloads/macos/"
    fi
    echo
    echo "Setup paused. Install Python, then run setup.command again."
    echo "Press any key to close this window..."
    read -n 1 -s
    exit 1
fi

echo "  Found Python: $PY_CMD"
"$PY_CMD" --version
echo

# ============================================================
# Step 2: Check for Google Chrome
# ============================================================
echo "[2/3] Looking for Google Chrome..."
CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -f "$CHROME_PATH" ]; then
    echo "  Chrome not found at standard location."
    if show_yes_no "Chrome Recommended" "Google Chrome is not installed.\n\nFilm Tracker uses Chrome to handle some retailers (B&H, KEH) that have anti-bot protection. Without Chrome, those will be skipped.\n\nClick OK to open the Chrome download page, or Cancel to continue without Chrome."; then
        open "https://www.google.com/chrome/"
        echo "Continuing without Chrome for now."
    fi
    sleep 2
else
    echo "  Chrome found."
fi
echo

# ============================================================
# Step 3: Install Python packages
# ============================================================
echo "[3/3] Installing Python packages..."
echo "  First time may take a few minutes. Please wait."
echo

# Upgrade pip silently
"$PY_CMD" -m pip install --quiet --upgrade pip 2>/dev/null

# Install all required packages
if ! "$PY_CMD" -m pip install --quiet curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio; then
    # Try with --user flag if system install fails (common on Mac with system Python)
    if ! "$PY_CMD" -m pip install --quiet --user curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio; then
        show_dialog "Installation Failed" "Could not install Python packages.\n\nThis is usually a network problem or a permission issue.\n\nTry:\n  - Make sure your internet is connected\n  - Open Terminal and run: $PY_CMD -m pip install --user curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio" stop
        echo "Press any key to close this window..."
        read -n 1 -s
        exit 1
    fi
fi
echo "  Python packages installed."
echo

echo "Installing Chromium browser for Playwright (one-time, ~150 MB)..."
if "$PY_CMD" -m playwright install chromium >/dev/null 2>&1; then
    echo "  Chromium installed."
else
    echo "  Warning: Chromium download failed. Tracker will still work but with reduced fallback options."
fi
echo

# ============================================================
# Make run_tracker.command executable
# ============================================================
chmod +x run_tracker.command 2>/dev/null

# ============================================================
# Done
# ============================================================
show_dialog "Setup Complete" "Setup is complete!\n\nTo use the tracker:\n  Double-click run_tracker.command\n\nFirst run will:\n  1. Open a Chrome window (this is normal)\n  2. Run for 5-15 minutes searching retailers\n  3. Automatically open the report in your browser\n\nAfter the first run, edit config.txt to customize what gets searched." note

echo "============================================================"
echo "  Setup complete! Double-click run_tracker.command to start."
echo "============================================================"
echo
echo "Press any key to close this window..."
read -n 1 -s
