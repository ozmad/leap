#!/bin/bash
#
# Remove the Leap Monitor Linux desktop installation.
# Removes the launcher, .desktop entry, and hicolor icon copies.
#
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

LAUNCHER="$HOME/.local/bin/leap-monitor"
DESKTOP="$HOME/.local/share/applications/leap-monitor.desktop"
ICON_HICOLOR="$HOME/.local/share/icons/hicolor"

REMOVED=no

if [ -f "$LAUNCHER" ]; then
    rm -f "$LAUNCHER"
    printf "${GREEN}  ✓ Removed launcher: %s${NC}\n" "$LAUNCHER"
    REMOVED=yes
fi

if [ -f "$DESKTOP" ]; then
    rm -f "$DESKTOP"
    printf "${GREEN}  ✓ Removed desktop entry: %s${NC}\n" "$DESKTOP"
    REMOVED=yes
fi

for size in 16 32 48 64 128 256 512; do
    ICON="$ICON_HICOLOR/${size}x${size}/apps/leap-monitor.png"
    if [ -f "$ICON" ]; then
        rm -f "$ICON"
        REMOVED=yes
    fi
done
if [ "$REMOVED" = "yes" ]; then
    printf "${GREEN}  ✓ Removed icons from hicolor theme${NC}\n"
fi

# Refresh caches.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$ICON_HICOLOR" 2>/dev/null || true
fi

if [ "$REMOVED" = "no" ]; then
    echo "  Monitor not installed on Linux (no files found)"
fi
