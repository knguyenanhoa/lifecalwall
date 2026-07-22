#!/usr/bin/env bash
# uninstall.sh — Remove the Life Calendar LaunchAgent (macOS)

set -euo pipefail

PLIST_NAME="com.lifecal.wallpaper"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

if [[ "$(uname)" != "Darwin" ]]; then
    echo "Uninstall script is macOS-only."
    echo "On Linux, simply remove the autostart entry you created manually."
    exit 0
fi

if [[ -f "$PLIST_PATH" ]]; then
    echo "==> Unloading LaunchAgent…"
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✓ LaunchAgent removed."
else
    echo "No LaunchAgent found at $PLIST_PATH"
fi

echo ""
echo "Note: config and wallpaper image are kept at ~/.lifecal/"
echo "Remove that directory manually if you want a clean uninstall:"
echo "  rm -rf ~/.lifecal"
