#!/usr/bin/env bash
# install.sh — Set up the Life Calendar Wallpaper
# Usage: bash install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"
PLIST_NAME="com.lifecal.wallpaper"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$PLIST_NAME.plist"

# --------------------------------------------------------------------------
# 1. Create virtual environment and install dependencies
# --------------------------------------------------------------------------
echo "==> Creating Python virtual environment…"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "==> Installing dependencies…"
pip install --quiet --upgrade pip
pip install --quiet -r "$REPO_DIR/requirements.txt"

# Optional: install rumps for a native macOS menu-bar icon
if [[ "$(uname)" == "Darwin" ]]; then
    echo "==> Installing rumps (macOS menu-bar support)…"
    pip install --quiet rumps || echo "   (rumps install skipped — will use fallback UI)"
fi

deactivate

# --------------------------------------------------------------------------
# 2. Write the launchd plist (macOS auto-start on login)
# --------------------------------------------------------------------------
if [[ "$(uname)" == "Darwin" ]]; then
    echo "==> Writing LaunchAgent plist → $PLIST_PATH"
    mkdir -p "$PLIST_DIR"

    PYTHON_BIN="$VENV_DIR/bin/python3"
    MAIN_PY="$REPO_DIR/main.py"

    # Log dir is still created so the Python rotating handler can write into it
    mkdir -p "$HOME/.lifecal/logs"

    cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>             <string>$PLIST_NAME</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$MAIN_PY</string>
    </array>
    <key>RunAtLoad</key>         <true/>
    <key>KeepAlive</key>         <true/>
    <key>WorkingDirectory</key>  <string>$REPO_DIR</string>
    <!-- Allow the process to show a menu-bar icon and interact with the GUI -->
    <key>ProcessType</key>       <string>Interactive</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

    # --------------------------------------------------------------------------
    # 3. Load the agent (starts it immediately and on every future login)
    # --------------------------------------------------------------------------
    echo "==> Loading LaunchAgent…"
    # Unload first in case a previous version is running
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load -w "$PLIST_PATH"

    echo ""
    echo "✓ Installed! Life Calendar is now running."
    echo "  Logs : $HOME/.lifecal/logs/lifecal.log (rotated, ~2 MB cap)"
    echo "  Plist: $PLIST_PATH"
    echo ""
    echo "  To open settings:"
    echo "    $PYTHON_BIN $MAIN_PY --settings"
    echo ""
    echo "  To uninstall:"
    echo "    bash $REPO_DIR/uninstall.sh"

else
    # --------------------------------------------------------------------------
    # Linux: print manual instructions
    # --------------------------------------------------------------------------
    PYTHON_BIN="$VENV_DIR/bin/python3"
    echo ""
    echo "✓ Dependencies installed."
    echo ""
    echo "  To start Life Calendar manually:"
    echo "    $PYTHON_BIN $REPO_DIR/main.py"
    echo ""
    echo "  To autostart on login, add the above command to your desktop"
    echo "  environment's startup applications (e.g. ~/.config/autostart/)."
    echo ""
    echo "  Example autostart entry (~/.config/autostart/lifecal.desktop):"
    echo "    [Desktop Entry]"
    echo "    Type=Application"
    echo "    Name=Life Calendar"
    echo "    Exec=$PYTHON_BIN $REPO_DIR/main.py"
    echo "    X-GNOME-Autostart-enabled=true"
fi
