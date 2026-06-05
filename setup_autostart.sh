#!/bin/bash
# Run ONCE on any machine to make Ginie auto-launch when this USB is plugged in.
# Usage: bash /path/to/this/setup_autostart.sh

set -e

UUID="3AA8-E066"
WATCH_SCRIPT="$HOME/.local/bin/ginie-watch.sh"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_FILE="$AUTOSTART_DIR/ginie-watch.desktop"

mkdir -p "$HOME/.local/bin" "$AUTOSTART_DIR"

# watcher script — runs as the logged-in user, has full display access
cat > "$WATCH_SCRIPT" << 'SCRIPT'
#!/bin/bash
UUID="3AA8-E066"
APP_LOCK="/tmp/ginie_app.lock"   # written by Ginie.py itself

was_mounted=0

while true; do
    MOUNT=$(findmnt -rn -S "UUID=$UUID" -o TARGET 2>/dev/null | head -1)

    if [ -n "$MOUNT" ]; then
        # USB is present
        if [ "$was_mounted" -eq 0 ]; then
            # fresh mount event — launch only if no instance already running
            was_mounted=1
            if [ ! -f "$APP_LOCK" ]; then
                python3 "$MOUNT/Ginie.py" &>/dev/null &
            fi
        fi
        # while mounted: do nothing (Ginie.py handles its own single-instance lock)
    else
        # USB removed — reset so next plug-in triggers a fresh launch
        was_mounted=0
    fi

    sleep 3
done
SCRIPT
chmod +x "$WATCH_SCRIPT"

# autostart .desktop — GNOME starts this on every login
cat > "$DESKTOP_FILE" << DESKTOP
[Desktop Entry]
Type=Application
Name=Ginie USB Watcher
Exec=$WATCH_SCRIPT
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
DESKTOP

echo ""
echo "Done. Log out and back in (or reboot) once."
echo "After that: plug in the USB and Ginie appears automatically."
echo "Unplug and re-plug to relaunch after closing."
echo ""
echo "To remove:"
echo "  rm '$WATCH_SCRIPT' '$DESKTOP_FILE'"
